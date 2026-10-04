"""Citation registry: every cited span is an exact slice of stored page text (absolute offsets)."""
from __future__ import annotations

import copy

from app.domain import Chunk, Citation

# ---------------------------------------------------------------------------------------------
# Citation book
# ---------------------------------------------------------------------------------------------
class CitationBook:
    def __init__(self):
        self.items: list[Citation] = []
        self._index: dict[tuple, str] = {}

    def add(self, chunk: Chunk, start: int, end: int, quote: str, score: float, role: str = "support", side: str | None = None,
            verified: bool = True) -> Citation:
        """`start`/`end` are absolute offsets in the page text."""
        key = (chunk.id, start, end)
        if key in self._index:
            c = next(x for x in self.items if x.id == self._index[key])
            if role == "conflict" and c.role != "conflict":
                c.role, c.side = role, side
            return c
        cid = f"S{len(self.items) + 1}"
        c = Citation(id=cid, doc_id=chunk.doc_id, doc_name=chunk.doc_name, page=chunk.page if chunk.paged else None, section=chunk.section,
                     quote=quote, passage=chunk.text, start=start, end=end, score=round(score, 3), ocr_conf=chunk.ocr_conf,
                     doc_date=chunk.doc_date, chunk_id=chunk.id, verified=verified, role=role, side=side)
        self.items.append(c)
        self._index[key] = cid
        return c


def loc(c: Citation) -> str:
    bits = [c.doc_name]
    if c.page:
        bits.append(f"p.{c.page}")
    if c.section:
        bits.append(f"§ {c.section}")
    return ", ".join(bits)


def attach_cites(cluster: dict, book: CitationBook, chunks: dict[str, Chunk]) -> dict:
    """Return a copy of a conflict cluster whose sources carry citation ids (and register the citations)."""
    cl = copy.deepcopy(cluster)
    for i, pos in enumerate(cl["positions"]):
        side = chr(ord("A") + i)
        for s in pos["sources"]:
            ch = chunks.get(s["chunk_id"])
            if ch is not None:
                s["cite"] = book.add(ch, s["start"], s["end"], s["sentence"], cl["score"], role="conflict", side=side).id
    return cl


