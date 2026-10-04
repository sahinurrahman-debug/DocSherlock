"""Rule-based answer composer - the deterministic fallback used when the LLM is disabled, unavailable or fails."""
from __future__ import annotations


from app.domain import Chunk, Quantity
from app.services.citations import CitationBook, attach_cites
from app.services.evidence import Context, Evidence
from app.services.uncertainty import ABSTAIN_BELOW, confidence
from app.utils.text import clip

# ---------------------------------------------------------------------------------------------
# Extractive composer
# ---------------------------------------------------------------------------------------------
def conflict_answer_lines(cl: dict) -> list[str]:
    lines = []
    for pos in cl["positions"]:
        srcs = []
        for s in pos["sources"]:
            d = f" ({s['doc_date']})" if s["doc_date"] else ""
            srcs.append(f"{s['doc_name']}{d} [{s['cite']}]" if s.get("cite") else f"{s['doc_name']}{d}")
        val = pos["value"] if cl["kind"] != "assertion" else f"“{clip(pos['sources'][0]['sentence'], 120)}”"
        lines.append(f"- **{val}** - " + "; ".join(srcs))
    return lines


def _same_value(a: Quantity, b: Quantity) -> bool:
    if isinstance(a.value, str) or isinstance(b.value, str):
        return a.value == b.value
    return abs(float(a.value) - float(b.value)) <= 0.03 * max(abs(float(a.value)), abs(float(b.value)), 1e-9)


def compose_extractive(ctx: Context, book: CitationBook, chunks: dict[str, Chunk]) -> dict:
    caveats: list[str] = []
    ev = ctx.evidence

    def insufficient(reason_conf: dict) -> dict:
        leads = ev[:2] if ev else []
        msg = "**I couldn't find a reliable answer to this in the uploaded documents.**"
        if ctx.missing_terms:
            msg += " The documents never mention " + ", ".join(f"*{t}*" for t in ctx.missing_terms[:4]) + "."
        if leads:
            ids = [book.add(e.chunk, e.page_start, e.page_end, e.text, e.score, role="lead").id for e in leads]
            msg += "\n\nClosest passages (shown for orientation only - they do not answer the question): " + " ".join(f"[{i}]" for i in ids)
        return {"status": "insufficient", "headline": "", "answer": msg, "confidence": reason_conf, "conflicts": [], "caveats": caveats}

    if not ev:
        return insufficient(confidence(ctx, 0, None, False))

    # ------- conflicts: report the disputed point, never a silent winner ---------------------
    if ctx.conflicts:
        lines = ["**The documents disagree on this - there is no single supported answer.**", ""]
        clusters = []
        for cl in ctx.conflicts:
            cl2 = attach_cites(cl, book, chunks)
            clusters.append(cl2)
            if len(ctx.conflicts) > 1:
                lines.append(f"*{', '.join(cl['topic'][:3]) or 'Disputed point'}*")
            lines += conflict_answer_lines(cl2)
            lines.append("")
        min_ocr = min((c.ocr_conf for c in book.items if c.ocr_conf is not None and c.role == "conflict"), default=None)
        conf_info = confidence(ctx, 0, min_ocr, True)
        first = clusters[0]
        vals = " vs ".join(p["value"] for p in first["positions"][:3])
        headline = vals if first["kind"] != "assertion" and len(vals) <= 60 else "Sources disagree"
        if first["time_scoped"]:
            caveats.append("The values may describe different points in time rather than contradict each other.")
        return {"status": "conflict", "headline": headline, "answer": "\n".join(lines).strip(), "confidence": conf_info,
                "conflicts": clusters, "caveats": caveats}

    # ------- standard answer -----------------------------------------------------------------
    top = ev[0]
    conf_pre = confidence(ctx, 1, top.chunk.ocr_conf, False)
    if conf_pre["score"] < ABSTAIN_BELOW:
        return insufficient(conf_pre)

    used: list[Evidence] = [top]
    for e in ev[1:]:
        if len(used) < 3 and e.score >= 0.65 * top.score and e.cov >= 0.5 * top.cov:
            used.append(e)

    headline = ""
    best_q = None
    if ctx.info.wants:
        terms = set(ctx.info.terms)
        best_key = None
        for rank, e in enumerate(used):
            for q in e.quantities:
                if q.kind in ctx.info.wants:
                    key = (len(terms & (q.ctx | {q.anchor})), -rank, -q.start)
                    if best_key is None or key > best_key:
                        best_q, best_key = q, key
    if best_q is None and ctx.info.qtype in ("quantity", "generic"):
        # no value of the expected kind: surface a value that sits right next to the question's own words
        terms = set(ctx.info.terms)
        best_key = None
        for rank, e in enumerate(used[:2]):
            for q in e.quantities:
                overlap = len(terms & (q.ctx | {q.anchor}))
                if overlap >= 2 and (best_key is None or (overlap, -rank, -q.start) > best_key):
                    best_q, best_key = q, (overlap, -rank, -q.start)
    if best_q is not None:
        headline = best_q.raw

    diverge = False
    if best_q is not None and len(used) > 1:
        other = []
        for e in used:
            for q in e.quantities:
                if q is best_q or q.kind != best_q.kind or q.unit != best_q.unit:
                    continue
                if len(q.ctx & best_q.ctx) >= 2 and not _same_value(q, best_q):
                    other.append(q.raw)
        if other:
            diverge = True
            caveats.append(f"Related passages mention a different value ({', '.join(sorted(set(other)))}) for a similar subject; "
                           "they were not judged to contradict each other, but check which applies.")

    cites = [book.add(e.chunk, e.page_start, e.page_end, e.text, e.score) for e in used]
    docs = {c.doc_id for c in cites}
    body = [f"{c.quote} [{c.id}]" for c in cites]
    text = body[0] if len(body) == 1 else "\n".join(f"- {l}" for l in body)

    min_ocr = min((c.ocr_conf for c in cites if c.ocr_conf is not None), default=None)
    conf_info = confidence(ctx, len(docs), min_ocr, False, diverge)
    if conf_info["score"] < ABSTAIN_BELOW:
        return insufficient(conf_info)
    if min_ocr is not None and min_ocr < 0.88:
        caveats.append(f"This comes from a scanned document (OCR confidence {min_ocr:.0%}); verify the figure against the original image.")
    if conf_info["label"] == "Low":
        caveats.append("Low confidence: the retrieved text only partly matches the question. Treat this as a lead, not a conclusion.")
    return {"status": "partial" if diverge else "answered", "headline": headline, "answer": text, "confidence": conf_info,
            "conflicts": [], "caveats": caveats}

