"""The Case File: what is worth a human's attention in a document set, found before anyone asks a question.

Deterministic - built only from the claims, conflict clusters and document metadata that ingestion already produced - so it works
with no LLM and costs nothing at request time (it is cached on the corpus snapshot).

Each finding is {id, type, severity, title, detail, evidence[], question?}. Evidence entries always carry the verbatim sentence and its offsets
so the UI can open the source with the passage highlighted. `detail` text may contain **bold** markers (rendered safely by the UI).
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from app.services.conflict_detector import _AMEND_NAME
from app.services.facts import date_sort_key
from app.services.supersession import likely_current, short_value, subject_phrase, topic_label
from app.utils.text import clip, find_injections

if TYPE_CHECKING:
    from app.services.corpus import Corpus

OCR_LOW = 0.90
MAX_CONFLICT_FINDINGS = 8
_SEV = {"high": 0, "medium": 1, "low": 2}
_TYPE_ORDER = {"injection": 0, "conflict": 1, "superseded": 2, "stale": 3, "unreadable": 4, "ocr": 5, "undated": 6}


def evidence_ref(src: dict, value: str | None = None) -> dict:
    return {"doc_id": src["doc_id"], "doc_name": src["doc_name"], "doc_date": src.get("doc_date"), "page": src.get("page"), "section": src.get("section", ""),
            "start": src["start"], "end": src["end"], "quote": src["sentence"], "value": value if value is not None else src.get("value", ""),
            "ocr_conf": src.get("ocr_conf")}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _title(cluster: dict) -> str:
    if cluster["kind"] == "assertion":
        return topic_label(cluster)
    vals = [short_value(p, 28) for p in cluster["positions"]]
    shown = " vs ".join(vals[:2]) + (f" (+{len(vals) - 2} more)" if len(vals) > 2 else "")
    return f"{subject_phrase(cluster)}: {shown}"


def _conflict_finding(cluster: dict) -> dict:
    cur = likely_current(cluster)
    detail = cluster["resolution"]
    scans = [s for p in cluster["positions"] for s in p["sources"] if s.get("ocr_conf") is not None and s["ocr_conf"] < OCR_LOW]
    if scans:
        s = scans[0]
        detail += f" One value was read from a scan (OCR {round(s['ocr_conf'] * 100)}%) - check it against the original page."
    return {
        "id": f"conflict-{cluster['id']}", "type": "conflict", "severity": cluster["severity"], "title": _title(cluster), "detail": detail,
        "evidence": [evidence_ref(s, p["value"]) for p in cluster["positions"] for s in p["sources"][:1]],
        "question": f"What do the documents say about {topic_label(cluster).lower()}?" if cluster["kind"] != "assertion" else None,
        "cluster_id": cluster["id"], "likely_current": cur["index"], "basis": cur["basis"],
        "same_document": cluster["same_document"], "time_scoped": cluster["time_scoped"],
    }


def _supersession_findings(clusters: list[dict], names: dict[str, str]) -> list[dict]:
    """Documents that a newer document contradicts: 'partly superseded' when the newer one is an amendment, otherwise 'may be out of date'."""
    pairs: dict[tuple[str, str], list[tuple[dict, dict, dict, bool]]] = defaultdict(list)
    for cl in clusters:
        if cl["same_document"] or cl["time_scoped"]:
            continue
        cur = likely_current(cl)
        if cur["index"] is None or not cur["source"]:
            continue
        newer = cur["source"]
        for i, p in enumerate(cl["positions"]):
            if i == cur["index"]:
                continue
            for s in p["sources"]:
                if s["doc_id"] != newer["doc_id"] and s.get("doc_date") and date_sort_key(s["doc_date"]) < date_sort_key(newer["doc_date"]):
                    pairs[(s["doc_id"], newer["doc_id"])].append((cl, s, newer, cur["basis"] == "amendment"))
    out = []
    for (old_id, new_id), items in pairs.items():
        old_name, new_name = names.get(old_id, "?"), names.get(new_id, "?")
        seen, topics, ev = set(), [], []
        for cl, old_s, new_s, _ in items:
            if cl["id"] in seen:
                continue
            seen.add(cl["id"])
            topics.append(subject_phrase(cl, 4))
            if len(ev) < 4:
                ev += [evidence_ref(old_s), evidence_ref(new_s)]
        n = len(seen)
        amended = _AMEND_NAME.search(new_name) is not None or any(a for *_, a in items)
        new_date = items[0][2].get("doc_date")
        topics = list(dict.fromkeys(topics))
        listing = "; ".join(f"\"{t}\"" for t in topics[:3]) + (f" and {n - min(n, 3)} more" if n > 3 else "")
        if amended:
            title, ftype = f"{old_name} is partly superseded by {new_name}", "superseded"
            detail = (f"**{new_name}** ({new_date}) uses amendment wording and changes {_plural(n, 'point')} stated in **{old_name}**: {listing}. "
                      f"Read the two together - the older document alone no longer tells the whole story.")
        else:
            title, ftype = f"{old_name} may be out of date", "stale"
            detail = (f"A newer document, **{new_name}** ({new_date}), disagrees with it on {_plural(n, 'point')}: {listing}. "
                      f"Nothing says the newer one replaces it, so confirm which is current before relying on {old_name}.")
        out.append({"id": f"{ftype}-{old_id}-{new_id}", "type": ftype, "severity": "high" if n >= 3 else "medium", "title": title, "detail": detail,
                    "evidence": ev, "question": None, "doc_id": old_id, "newer_doc_id": new_id, "points": n})
    return out


def _injection_findings(corpus: "Corpus") -> list[dict]:
    """Documents containing sentences that try to give instructions to an AI assistant - reported as a security finding, never obeyed."""
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for ch in corpus.chunks:
        for a, b in find_injections(ch.text):
            by_doc[ch.doc_id].append({"doc_id": ch.doc_id, "doc_name": ch.doc_name, "doc_date": ch.doc_date, "page": ch.page if ch.paged else None, "section": ch.section,
                                      "start": ch.start + a, "end": ch.start + b, "quote": ch.text[a:b].strip(), "value": "", "ocr_conf": ch.ocr_conf})
    out = []
    for doc_id, refs in by_doc.items():
        name = refs[0]["doc_name"]
        out.append({"id": f"injection-{doc_id}", "type": "injection", "severity": "high", "title": f"{name} contains instructions aimed at AI assistants",
                    "detail": (f"**{name}** includes {_plural(len(refs), 'sentence')} that try to give orders to an AI reading it. DocSherlock treats this as document text only: "
                               "it is never followed, never used as evidence, and removed from what the language model sees. Check where this document came from."),
                    "evidence": refs[:3], "question": None, "doc_id": doc_id})
    return out


def build_casefile(corpus: "Corpus") -> dict:
    clusters = corpus.clusters
    docs = corpus.docs
    names = {d.id: d.name for d in docs.values()}
    findings: list[dict] = []

    conflict_findings = [_conflict_finding(c) for c in clusters]
    findings += conflict_findings[:MAX_CONFLICT_FINDINGS]
    omitted = max(0, len(conflict_findings) - MAX_CONFLICT_FINDINGS)
    sup = _supersession_findings(clusters, names)
    findings += sup

    inj = _injection_findings(corpus)
    findings += inj
    with_text = {c.doc_id for c in corpus.chunks}
    empty = [d for d in docs.values() if d.id not in with_text]
    if empty:
        findings.append({"id": "unreadable", "type": "unreadable", "severity": "high",
                         "title": f"{_plural(len(empty), 'document')} could not be read",
                         "detail": "No searchable text was found in " + ", ".join(f"**{d.name}**" for d in empty[:4]) +
                                   ". Nothing in them can be cited or checked - try a clearer copy or a text-based export.",
                         "evidence": [], "question": None})
    scans = [d for d in docs.values() if d.ocr_conf is not None and d.ocr_conf < OCR_LOW and d.id in with_text]
    if scans:
        findings.append({"id": "ocr", "type": "ocr", "severity": "medium",
                         "title": f"{_plural(len(scans), 'scan')} read with limited accuracy",
                         "detail": "; ".join(f"**{d.name}** (OCR {round((d.ocr_conf or 0) * 100)}%)" for d in scans[:4]) +
                                   ". Numbers and names from these pages should be checked against the original image (the source viewer shows it).",
                         "evidence": [], "question": None})
    undated = [d for d in docs.values() if not d.doc_date]
    if undated:
        findings.append({"id": "undated", "type": "undated", "severity": "low",
                         "title": f"{_plural(len(undated), 'document')} without a date",
                         "detail": ", ".join(f"**{d.name}**" for d in undated[:4]) + (" and more" if len(undated) > 4 else "") +
                                   ": without a date DocSherlock cannot tell whether it is newer or older than the others, which weakens any 'which is current' reasoning. "
                                   "Set the date on the document (click its date chip).",
                         "evidence": [], "question": None})

    findings.sort(key=lambda f: (_SEV[f["severity"]], _TYPE_ORDER[f["type"]]))

    involved: dict[str, int] = defaultdict(int)
    corroborated = 0
    for cl in clusters:
        in_cluster = {s["doc_id"] for p in cl["positions"] for s in p["sources"]}
        for did in in_cluster:
            involved[did] += 1
        corroborated += sum(1 for p in cl["positions"] if len({s["doc_id"] for s in p["sources"]}) >= 2)
    overridden: dict[str, list[str]] = defaultdict(list)
    for f in sup:
        overridden[f["doc_id"]].append(names.get(f["newer_doc_id"], ""))

    high = sum(1 for c in clusters if c["severity"] == "high")
    parts = [f"{_plural(len(docs), 'document')} and {_plural(len(corpus.facts), 'claim')} checked."]
    if clusters:
        parts.append(f"{_plural(len(clusters), 'point')} {'is' if len(clusters) == 1 else 'are'} disputed, touching {_plural(len(involved), 'document')}"
                     + (f" ({high} high severity)." if high else "."))
    else:
        parts.append("No contradictions were found - the documents agree wherever they overlap.")
    if sup:
        parts.append(f"{_plural(len(sup), 'document')} {'is' if len(sup) == 1 else 'are'} superseded or possibly out of date.")

    questions = [f["question"] for f in conflict_findings if f.get("question")][:4]
    questions += [q for q in ("Summarise the key obligations in these documents.", "Do any documents contradict each other?") if q not in questions]

    return {
        "briefing": " ".join(parts),
        "stats": {"documents": len(docs), "claims": len(corpus.facts), "disputed_points": len(clusters), "high_severity": high,
                  "documents_in_dispute": len(involved), "corroborated_points": corroborated, "superseded_documents": len(sup),
                  "scans": sum(1 for d in docs.values() if d.ocr_conf is not None), "undated": len(undated)},
        "findings": findings, "findings_total": len(findings) + omitted, "omitted_conflicts": omitted,
        "documents": [{"id": d.id, "name": d.name, "doc_date": d.doc_date, "disputed_points": involved.get(d.id, 0),
                       "overridden_by": sorted(set(overridden.get(d.id, []))), "ocr_conf": d.ocr_conf, "readable": d.id in with_text} for d in docs.values()],
        "suggested_questions": [clip(q, 120) for q in questions[:6]],
    }
