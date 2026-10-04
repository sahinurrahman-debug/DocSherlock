"""The Case Board: documents, the claims they disagree about, and the strings between them, as plain data for the UI to draw.

  documents  every readable document (so unconnected ones can be shown as such)
  disputes   each disputed point with its positions; a position lists the documents that state that value
  amends     document -> document edges: the newer one amends / supersedes (or may have outdated) the older one on N points

Nothing is invented here: it is a re-shaping of the conflict clusters and the Case File's supersession findings, so the board can never
show a link the rest of the app wouldn't also report.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.casefile import evidence_ref
from app.services.supersession import likely_current, subject_phrase, topic_label

if TYPE_CHECKING:
    from app.services.corpus import Corpus

MAX_DISPUTES = 14


def build_board(corpus: "Corpus") -> dict:
    clusters = corpus.clusters[:MAX_DISPUTES]
    involved: dict[str, int] = {}
    disputes = []
    for cl in clusters:
        cur = likely_current(cl)
        positions = []
        for i, p in enumerate(cl["positions"]):
            docs_in_position = {s["doc_id"] for s in p["sources"]}
            positions.append({"index": i, "value": p["value"], "current": cur["index"] == i, "corroborated": len(docs_in_position) >= 2,
                              "sources": [evidence_ref(s, p["value"]) for s in p["sources"]]})
            for d in docs_in_position:
                involved[d] = involved.get(d, 0) + 1
        disputes.append({"id": cl["id"], "title": subject_phrase(cl) if cl["kind"] != "assertion" else topic_label(cl), "severity": cl["severity"], "kind": cl["kind"],
                         "same_document": cl["same_document"], "time_scoped": cl["time_scoped"], "resolution": cl["resolution"],
                         "likely_current": cur["index"], "basis": cur["basis"], "positions": positions})
    amends = [{"newer_doc_id": f["newer_doc_id"], "older_doc_id": f["doc_id"], "points": f["points"], "kind": f["type"]}
              for f in corpus.casefile["findings"] if f["type"] in ("superseded", "stale")]
    docs = sorted(corpus.docs.values(), key=lambda d: (d.doc_date or "9999", d.name))
    return {
        "documents": [{"id": d.id, "name": d.name, "doc_date": d.doc_date, "ext": d.name.rsplit(".", 1)[-1].lower() if "." in d.name else "", "disputes": involved.get(d.id, 0)}
                      for d in docs],
        "disputes": disputes, "amends": amends,
        "stats": {"documents": len(docs), "disputes": len(disputes), "shown_of": len(corpus.clusters), "strings": sum(len(d["positions"]) for d in disputes)},
    }
