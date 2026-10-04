"""Which position in a disputed point is the *likely current* one, and why.

Shared by the Case File, the Timeline ("as of") and the Case Board. Everything here is inference from document dates and wording -
no document is ever claimed to say more than it does - and every result carries its `basis` so the UI can label it as such.

basis:
  "amendment"  a position backed by amendment / supersession wording whose newest formal source post-dates every other position
  "recency"    all positions are dated and one is strictly newest (weaker: nothing says it replaces the others)
  None         the dates / wording do not settle it
"""
from __future__ import annotations

from app.services.conflict_detector import _AMEND_NAME, _INFORMAL_NAME, _SUPERSEDE
from app.services.facts import date_sort_key


def _newest(sources: list[dict]) -> dict | None:
    dated = [s for s in sources if s.get("doc_date")]
    return max(dated, key=lambda s: date_sort_key(s["doc_date"])) if dated else None


def _oldest(sources: list[dict]) -> dict | None:
    dated = [s for s in sources if s.get("doc_date")]
    return min(dated, key=lambda s: date_sort_key(s["doc_date"])) if dated else None


def position_facts(position: dict) -> dict:
    """Dates and wording of one position's sources."""
    srcs = position["sources"]
    formal = [s for s in srcs if not _INFORMAL_NAME.search(s["doc_name"])]
    newest, oldest = _newest(srcs), _oldest(srcs)
    fnewest = _newest(formal)
    amend = [s for s in srcs if _SUPERSEDE.search(s["sentence"]) or _AMEND_NAME.search(s["doc_name"])]
    return {
        "newest": date_sort_key(newest["doc_date"]) if newest else "", "oldest": date_sort_key(oldest["doc_date"]) if oldest else "",
        "newest_source": newest, "oldest_source": oldest,
        "formal_newest": date_sort_key(fnewest["doc_date"]) if fnewest else "", "formal_newest_source": fnewest,
        "amends": bool(amend), "amend_source": _newest(amend) or (amend[0] if amend else None),
        "has_formal": bool(formal),
    }


def likely_current(cluster: dict) -> dict:
    """{index, basis, source, others_later} for a conflict cluster (see module docstring)."""
    positions = cluster["positions"]
    facts = [position_facts(p) for p in positions]
    for i, me in enumerate(facts):
        others = [f for j, f in enumerate(facts) if j != i]
        ref_dates = [o["formal_newest"] or o["newest"] for o in others]
        if me["amends"] and me["formal_newest"] and all(ref_dates) and all(me["formal_newest"] > d for d in ref_dates):
            later = [s for j, p in enumerate(positions) if j != i for s in p["sources"]
                     if s.get("doc_date") and date_sort_key(s["doc_date"]) > me["formal_newest"]]
            return {"index": i, "basis": "amendment", "source": me["formal_newest_source"], "others_later": later}
    if all(f["newest"] for f in facts):
        order = sorted(range(len(facts)), key=lambda i: facts[i]["newest"], reverse=True)
        if len(order) > 1 and facts[order[0]]["newest"] > facts[order[1]]["newest"]:
            return {"index": order[0], "basis": "recency", "source": facts[order[0]]["newest_source"], "others_later": []}
    return {"index": None, "basis": None, "source": None, "others_later": []}


def topic_label(cluster: dict) -> str:
    """A readable subject for a disputed point, e.g. 'payment terms date'."""
    words = [w for w in cluster.get("topic", [])[:3] if w]
    if cluster.get("kind") == "assertion":
        return "Opposing statements on " + (" ".join(words) or "the same subject")
    return (" ".join(words) or "the same subject").capitalize()


def subject_phrase(cluster: dict, words: int = 5) -> str:
    """A human-readable subject: the first source sentence with the disputed value blanked out ('Invoices are payable ___ from the invoice date').
    Keeps up to `words` whole words either side of the blank."""
    import re
    if cluster.get("kind") != "assertion" and cluster["positions"]:
        pos = cluster["positions"][0]
        sentence = " ".join(pos["sources"][0]["sentence"].split())
        value = pos["value"]
        idx = sentence.lower().find(value.lower()) if value else -1
        if idx >= 0:
            before = re.sub(r"^(?:\d+(?:\.\d+)*\.?|[A-Za-z]\.|[-*•])\s+", "", sentence[:idx].strip()).split()      # drop list / section numbering
            after = sentence[idx + len(value):].strip().rstrip(".;:").split()
            left = ("… " if len(before) > words else "") + " ".join(before[-words:])
            right = " ".join(after[:words]) + (" …" if len(after) > words else "")
            phrase = " ".join(x for x in (left.strip(), "___", right.strip()) if x)
            phrase = re.sub(r"\s+([,;:.])", r"\1", phrase)
            if len(before) + len(after) >= 2:
                return phrase[0].upper() + phrase[1:]
    return topic_label(cluster)


def short_value(position: dict, limit: int = 48) -> str:
    v = position["value"]
    return v if len(v) <= limit else v[: limit - 1].rstrip() + "…"
