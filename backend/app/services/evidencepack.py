"""Evidence Pack: one answer as a self-contained PDF a reviewer, auditor or lawyer can check without DocSherlock.

  page 1      question, answer, confidence and the reasons behind it, caveats, conflicts, the Red-Team verdict if one was run, and a statement of what
              was re-verified when the pack was generated
  evidence    one section per cited passage: the verbatim quote highlighted, and the original page image with the passage marked (PDF / scans),
              or the surrounding text with the passage highlighted (Word, text, e-mail ...)
  appendix    the evidence matrix and the documents used, with SHA-256 fingerprints of the exact files that were uploaded

All document text is HTML-escaped before it goes into the layout. Quotes are re-checked against the stored page text at generation time.
"""
from __future__ import annotations

import html
import io
import re
from datetime import datetime, timezone

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, settings
from app.models.document import Document, Page
from app.models.investigation import Question
from app.services import ingestion
from app.services.render import render_page

MAX_EVIDENCE = 12
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_TONE = {"HIGH": "#1f6f3f", "MEDIUM": "#86560f", "LOW": "#a4452a", "CONFLICTED": "#a4452a", "INSUFFICIENT": "#555566"}
_VERDICT = {"survived": "#1f6f3f", "weakened": "#86560f", "refuted": "#a4452a"}

CSS = """
body { font-family: sans-serif; font-size: 10pt; color: #222; line-height: 1.35; }
h1 { font-family: serif; font-size: 22pt; margin: 0 0 2pt 0; }
h2 { font-family: serif; font-size: 14pt; margin: 14pt 0 4pt 0; }
h3 { font-family: serif; font-size: 11.5pt; margin: 10pt 0 3pt 0; }
.muted { color: #666; font-size: 8.5pt; }
.badge { padding: 1pt 5pt; font-weight: bold; }
.q { background-color: #f3efe6; padding: 6pt; margin: 4pt 0; }
.quote { background-color: #fff3c4; padding: 5pt; margin: 4pt 0; border-left: 3pt solid #c98a2b; }
.mark { background-color: #ffe58a; }
.mono { font-family: monospace; font-size: 8pt; color: #333; }
.row { margin: 2pt 0; }
.small { font-size: 8.5pt; }
"""


def _logo_png() -> bytes | None:
    """The DocSherlock logo as a PNG for the cover, rendered from the same `favicon.svg` the app and README use (one source of truth)."""
    for path in (settings.frontend_dist / "favicon.svg", ROOT_DIR / "frontend" / "public" / "favicon.svg"):
        try:
            if path.is_file():
                svg = pymupdf.open(stream=path.read_bytes(), filetype="svg")
                return svg[0].get_pixmap(matrix=pymupdf.Matrix(160 / 32, 160 / 32), alpha=False).tobytes("png")
        except Exception:                                    # a missing or unreadable logo must never stop the pack from being built
            continue
    return None


def _e(text: str | None) -> str:
    return html.escape(" ".join((text or "").split()), quote=True)


def _rich(text: str) -> str:
    """Escape, then re-apply **bold**; bullets become list items; [S#] markers stay visible."""
    out, items = [], []
    for raw in (text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        bullet = line.startswith("- ")
        body = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", html.escape(line[2:] if bullet else line, quote=True))
        if bullet:
            items.append(f"<li>{body}</li>")
        else:
            if items:
                out.append("<ul>" + "".join(items) + "</ul>")
                items = []
            out.append(f"<p>{body}</p>")
    if items:
        out.append("<ul>" + "".join(items) + "</ul>")
    return "".join(out)


def _loc(c: dict) -> str:
    return " · ".join(x for x in (c.get("doc_name"), f"page {c['page']}" if c.get("page") else None, f"section “{c['section']}”" if c.get("section") else None,
                                  c.get("doc_date")) if x)


def build_pack(db: Session, row: Question) -> bytes:
    p = dict(row.payload or {})
    cites = [c for c in p.get("citations", []) if c.get("role") != "lead"]
    leads = [c for c in p.get("citations", []) if c.get("role") == "lead"]
    now = datetime.now(timezone.utc)
    archive = pymupdf.Archive()
    docs: dict[str, Document] = {}
    page_cache: dict[tuple[str, int], Page | None] = {}

    def page_row(doc_id: str, page: int | None) -> Page | None:
        key = (doc_id, page or 1)
        if key not in page_cache:
            page_cache[key] = db.scalar(select(Page).where(Page.document_id == doc_id, Page.page_number == (page or 1)))
        return page_cache[key]

    def doc_of(doc_id: str) -> Document | None:
        if doc_id not in docs:
            docs[doc_id] = db.get(Document, doc_id)
        return docs[doc_id]

    # ---- re-verify every quote now ------------------------------------------------------------------------------------
    verified = 0
    for c in cites:
        pg = page_row(c["doc_id"], c.get("page"))
        if pg is not None and pg.text[c["start"]:c["end"]] == c["quote"]:
            verified += 1

    h: list[str] = []
    level = p.get("level", "")
    conf = p.get("confidence", {})
    logo = _logo_png()
    if logo:
        archive.add(logo, "logo.png")
        h.append('<p style="margin:0 0 6pt 0"><img src="logo.png" style="width:34pt;height:34pt"/></p>')
    h.append("<h1>DocSherlock evidence pack</h1>")
    h.append(f'<p class="muted">Generated {now.strftime("%d %b %Y, %H:%M UTC")} · answer <span class="mono">{_e(row.id)}</span> · investigation <span class="mono">{_e(row.investigation_id)}</span></p>')
    h.append(f'<h3>Question</h3><div class="q">{_e(p.get("question"))}</div>')
    if p.get("as_of"):
        a = p["as_of"]
        h.append(f'<p class="small"><b>Answered as of {_e(a["date"])}</b> using {a["documents_used"]} of {a["documents_total"]} documents that existed by then.</p>')
    h.append(f'<h3>Answer</h3><p><span class="badge" style="color:#fff;background-color:{_TONE.get(level, "#555")}">{_e(level)}</span> '
             f'<span class="small">confidence {round(float(conf.get("score", 0)) * 100)}% · {_e(p.get("status"))}</span></p>')
    if p.get("headline"):
        h.append(f"<h2>{_e(p['headline'])}</h2>")
    h.append(_rich(p.get("answer", "")))
    eng = p.get("engine", {})
    h.append(f'<p class="muted">Written by {"the rule-based engine" if eng.get("name") == "rules" else _e(eng.get("model") or eng.get("name"))}'
             f'{" (fallback: " + _e(eng.get("reason")) + ")" if eng.get("fallback") and eng.get("reason") else ""}. Every quote below is reproduced from the stored document text.</p>')

    if conf.get("reasons"):
        h.append("<h3>Why this level</h3>")
        for r in conf["reasons"]:
            sign = {"+": "+", "-": "−"}.get(r.get("effect", ""), "·")
            h.append(f'<div class="row small"><b>{sign}</b> {_e(r.get("text"))}</div>')
    if p.get("caveats"):
        h.append("<h3>Caveats</h3>" + "".join(f'<div class="row small">• {_e(c)}</div>' for c in p["caveats"]))
    for cl in p.get("conflicts", []):
        h.append(f'<h3>Disputed point: {_e(" ".join(cl.get("topic", [])[:3]))}</h3><p class="small">{_e(cl.get("explanation"))}</p>')
        for pos in cl.get("positions", []):
            srcs = "; ".join(f"{s['doc_name']}{' (' + s['doc_date'] + ')' if s.get('doc_date') else ''}" for s in pos["sources"])
            h.append(f'<div class="row"><b>{_e(pos["value"])}</b> <span class="small">— {_e(srcs)}</span></div>')
        if cl.get("resolution"):
            h.append(f'<div class="small" style="margin-top:3pt">{_rich(cl["resolution"])}<i>Inference, not stated in the documents.</i></div>')
    rt = p.get("redteam")
    if rt:
        h.append(f'<h3>Red-team review</h3><p><span class="badge" style="color:#fff;background-color:{_VERDICT.get(rt["verdict"], "#555")}">{_e(rt["verdict"]).upper()}</span> '
                 f'<span class="small">{_e(rt["headline"])}</span></p>')
        for c in rt["checks"]:
            tag = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}[c["status"]]
            h.append(f'<div class="row small"><b>{tag}</b> {_e(c["label"])} — {_e(c["detail"])}</div>')
    h.append(f'<h3>What was checked when this pack was generated</h3><p class="small">{verified} of {len(cites)} cited quotes were compared with the stored page text at their '
             f'recorded positions and {"all match exactly" if verified == len(cites) else "<b>not all match - treat this pack with caution</b>"}. '
             f'The SHA-256 fingerprints in the appendix identify the exact files that were uploaded.</p>')

    # ---- one section per cited passage ----------------------------------------------------------------------------------
    for n, c in enumerate(cites[:MAX_EVIDENCE]):
        pg, doc = page_row(c["doc_id"], c.get("page")), doc_of(c["doc_id"])
        h.append(f'<div style="page-break-before:always"></div><h2>{_e(c["id"])} · {_e(c["doc_name"])}</h2><p class="muted">{_e(_loc(c))}'
                 f'{" · OCR " + str(round(c["ocr_conf"] * 100)) + "%" if c.get("ocr_conf") is not None else ""}{" · role: " + _e(c.get("role")) if c.get("role") not in (None, "support") else ""}</p>')
        h.append(f'<div class="quote">“{_e(c["quote"])}”</div>')
        png = None
        if pg is not None and doc is not None:
            path = ingestion.ensure_file(db, doc)
            if path is not None:
                try:
                    png = render_page(path, doc.file_type, pg, pg.text[c["start"]:c["end"]], 1.5)
                except Exception:                                   # a page that cannot be drawn still gets its text excerpt
                    png = None
        if png:
            name = f"page{n}.png"
            archive.add(png, name)
            h.append(f'<p class="small muted">The original page, with the cited passage marked:</p><img src="{name}" style="width:430pt"/>')
        elif pg is not None:
            a, b = c["start"], c["end"]
            before, quote, after = pg.text[max(0, a - 280):a], pg.text[a:b], pg.text[b:b + 280]
            h.append(f'<p class="small muted">The surrounding text, with the cited passage highlighted:</p><p class="small">{"…" if a > 280 else ""}{_e(before)} '
                     f'<span class="mark">{_e(quote)}</span> {_e(after)}{"…" if len(pg.text) > b + 280 else ""}</p>')
    if len(cites) > MAX_EVIDENCE:
        h.append(f'<p class="small muted">{len(cites) - MAX_EVIDENCE} further citation(s) are listed in the appendix only.</p>')

    # ---- appendix ---------------------------------------------------------------------------------------------------------
    h.append('<div style="page-break-before:always"></div><h2>Appendix A · Evidence matrix</h2>')
    matrix = p.get("evidence_matrix") or []
    if matrix:
        for m in matrix:
            h.append(f'<div class="row small"><b>{_e(m.get("value") or "—")}</b> · {_e(m.get("subject"))} — {_e(m.get("document"))}'
                     f'{", p." + str(m["page"]) if m.get("page") else ""} [{_e(m.get("cite"))}]</div>')
    else:
        h.append('<p class="small">No structured claims were recorded for this answer.</p>')
    if len(cites) > MAX_EVIDENCE:
        for c in cites[MAX_EVIDENCE:]:
            h.append(f'<div class="row small">{_e(c["id"])} · {_e(_loc(c))} — “{_e(c["quote"])}”</div>')
    if leads:
        h.append("<h3>Closest passages (shown for orientation only, not used as evidence)</h3>" + "".join(f'<div class="row small">{_e(c["id"])} · {_e(_loc(c))}</div>' for c in leads))
    h.append("<h2>Appendix B · Documents</h2>")
    used = {c["doc_id"] for c in p.get("citations", [])} | {s["doc_id"] for cl in p.get("conflicts", []) for ps in cl["positions"] for s in ps["sources"]}
    for did in sorted(used):
        d = doc_of(did)
        if d:
            h.append(f'<div class="row small"><b>{_e(d.filename)}</b> · {_e(d.doc_date or "undated")} · {d.file_size:,} bytes<br/><span class="muted">SHA-256 </span><span class="mono">{d.sha256}</span></div>')

    story = pymupdf.Story(html=f"<html><body>{''.join(h)}</body></html>", user_css=CSS, archive=archive)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (48, 48, -48, -56)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()

    doc = pymupdf.open("pdf", buf.getvalue())
    total = len(doc)
    for i, pg in enumerate(doc):
        pg.insert_text((48, mediabox.height - 28), f"DocSherlock evidence pack - answer {row.id} - page {i + 1} of {total}", fontsize=8, color=(0.45, 0.45, 0.45))
    doc.set_metadata({"title": f"DocSherlock evidence pack - {row.question[:80]}", "author": "DocSherlock", "subject": f"Answer {row.id}", "creator": "DocSherlock"})
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out
