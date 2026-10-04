"""Time-travel: what did the documents say *on a given date*?

Documents supersede each other (a contract, then an amendment, then an e-mail). For any date D this module reports, for every disputed point,
which position was in force using only the documents that existed by D - and it can restrict a question to exactly those documents.

Rules (all inference from document dates and wording; every result says which rule applied):
  * a document counts from its document date; a partial date ("2024-03", "2024") counts from the start of its period
  * undated documents cannot be placed in time, so they are excluded from an "as of" view (and the view says so)
  * one known position            -> "settled"  (that value, per its newest known source)
  * several, one clearly current  -> "likely"   (amendment wording that post-dates the others, or strictly newest - see supersession.py)
  * several, nothing settles it   -> "disputed"
  * no known source yet           -> "not_yet"  (positions that only appear later are listed under `upcoming`)
"""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from app.services.casefile import evidence_ref
from app.services.facts import date_sort_key
from app.services.supersession import likely_current, subject_phrase, topic_label

if TYPE_CHECKING:
    from app.services.corpus import Corpus

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_day(value: str) -> str:
    """Validate 'YYYY-MM-DD' and return it; raises ValueError otherwise."""
    if not _ISO_DAY.match(value or ""):
        raise ValueError("Use a date like 2024-01-15.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("That is not a real calendar date.") from None
    return value


def doc_key(doc_date: str | None) -> str:
    return date_sort_key(doc_date) if doc_date else ""


def documents_as_of(corpus: "Corpus", day: str) -> tuple[list[str], list[dict]]:
    """(ids of documents that existed on `day`, the rest with the reason they are left out)."""
    keep, out = [], []
    for d in corpus.docs.values():
        k = doc_key(d.doc_date)
        if not k:
            out.append({"doc_id": d.id, "name": d.name, "doc_date": None, "reason": "undated"})
        elif k > day:
            out.append({"doc_id": d.id, "name": d.name, "doc_date": d.doc_date, "reason": "later"})
        else:
            keep.append(d.id)
    return keep, out


def _known(cluster: dict, day: str) -> dict:
    """The cluster restricted to sources that already existed on `day` (positions with no known source disappear)."""
    positions = []
    for p in cluster["positions"]:
        srcs = [s for s in p["sources"] if s.get("doc_date") and doc_key(s["doc_date"]) <= day]
        if srcs:
            positions.append({"value": p["value"], "sources": srcs})
    return {**cluster, "positions": positions}


def _newest(sources: list[dict]) -> dict:
    return max(sources, key=lambda s: doc_key(s.get("doc_date")))


def snapshot_topic(cluster: dict, day: str) -> dict:
    known = _known(cluster, day)
    upcoming = []
    for p in cluster["positions"]:
        later = [s for s in p["sources"] if s.get("doc_date") and doc_key(s["doc_date"]) > day]
        if later and not any(doc_key(s.get("doc_date")) <= day for s in p["sources"] if s.get("doc_date")):
            first = min(later, key=lambda s: doc_key(s["doc_date"]))
            upcoming.append({"value": p["value"], "date": first["doc_date"], "doc_name": first["doc_name"], "doc_id": first["doc_id"]})
    upcoming.sort(key=lambda u: doc_key(u["date"]))
    base = {"cluster_id": cluster["id"], "title": subject_phrase(cluster), "label": topic_label(cluster), "kind": cluster["kind"], "severity": cluster["severity"],
            "upcoming": upcoming, "positions_known": len(known["positions"]), "value": None, "basis": None, "source": None, "note": ""}
    pos = known["positions"]
    if not pos:
        return {**base, "status": "not_yet"}
    if len(pos) == 1:
        src = _newest(pos[0]["sources"])
        return {**base, "status": "settled", "value": pos[0]["value"], "basis": "only position documented by then", "source": evidence_ref(src, pos[0]["value"])}
    cur = likely_current(known)
    if cur["index"] is not None:
        win = pos[cur["index"]]
        src = cur["source"] or _newest(win["sources"])
        note = ""
        if cur["others_later"]:
            s = cur["others_later"][0]
            note = (f"A later source, {s['doc_name']} ({s['doc_date']}), still gives a different value - informal messages do not override a formal amendment, "
                    f"but the change may not have been applied in practice.")
        return {**base, "status": "likely", "value": win["value"], "basis": "amendment wording" if cur["basis"] == "amendment" else "most recent source",
                "source": evidence_ref(src, win["value"]), "note": note,
                "alternatives": [p["value"] for i, p in enumerate(pos) if i != cur["index"]]}
    return {**base, "status": "disputed", "alternatives": [p["value"] for p in pos],
            "note": "The documents that existed by then disagree and nothing in their dates or wording shows which prevails."}


def build_timeline(corpus: "Corpus", day: str | None = None) -> dict:
    docs = sorted(corpus.docs.values(), key=lambda d: (doc_key(d.doc_date) or "9999", d.name))
    dated = [d for d in docs if d.doc_date]
    clusters = [c for c in corpus.clusters if not c["same_document"]]

    # which documents introduce a *new* value for a disputed point (an amendment changing a contract term, a handbook changing a policy)
    introduces: dict[str, list[dict]] = {}
    for c in clusters:
        firsts = []
        for p in c["positions"]:
            dated_src = [s for s in p["sources"] if s.get("doc_date")]
            if dated_src:
                f = min(dated_src, key=lambda s: doc_key(s["doc_date"]))
                firsts.append((doc_key(f["doc_date"]), f, p["value"]))
        firsts.sort(key=lambda t: t[0])
        for _, f, value in firsts[1:]:
            introduces.setdefault(f["doc_id"], []).append({"cluster_id": c["id"], "title": subject_phrase(c), "value": value})

    out = {
        "documents": [{"id": d.id, "name": d.name, "doc_date": d.doc_date, "key": doc_key(d.doc_date), "dated": bool(d.doc_date),
                       "introduces": introduces.get(d.id, [])} for d in docs],
        "range": {"min": doc_key(dated[0].doc_date) if dated else None, "max": doc_key(dated[-1].doc_date) if dated else None},
        "undated": [d.name for d in docs if not d.doc_date],
        "topics": [{"cluster_id": c["id"], "title": subject_phrase(c), "severity": c["severity"],
                    "history": sorted(({"date": s["doc_date"], "doc_id": s["doc_id"], "doc_name": s["doc_name"], "value": p["value"]}
                                       for p in c["positions"] for s in p["sources"] if s.get("doc_date")), key=lambda h: (doc_key(h["date"]), h["doc_name"]))}
                   for c in clusters],
    }
    if day:
        keep, excluded = documents_as_of(corpus, day)
        out["as_of"] = {"date": day, "documents_used": len(keep), "documents_total": len(corpus.docs), "excluded": excluded,
                        "topics": [snapshot_topic(c, day) for c in clusters]}
    return out
