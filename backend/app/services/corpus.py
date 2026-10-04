"""Per-scope corpus snapshots (a session plus an optional subset of documents), cached and invalidated on change.

A snapshot holds everything the answer path needs without touching the database again: the chunks, the lexical index, the
claims (as `Fact` objects) and the disputed points (conflict clusters) found among them.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import Chunk, Fact
from app.models.document import Claim, DocChunk, Document
from app.services.claims import fact_from_dict
from app.services.conflict_detector import ConflictEngine, cluster_conflicts
from app.services.embeddings import EmbeddingService
from app.services.retriever import HybridRetriever, LexicalIndex

if TYPE_CHECKING:
    from app.services.vectorstore import VectorStore


@dataclass
class DocInfo:
    id: str
    name: str
    doc_date: str | None
    title: str | None
    paged: bool
    ocr_conf: float | None


@dataclass
class Corpus:
    session_id: str
    doc_ids: list[str] | None
    docs: dict[str, DocInfo]
    chunks: list[Chunk]
    chunk_by_id: dict[str, Chunk]
    facts: list[Fact]
    lexical: LexicalIndex
    _clusters: list[dict] | None = field(default=None, repr=False)
    _casefile: dict | None = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def clusters(self) -> list[dict]:
        with self._lock:
            if self._clusters is None:
                conflicts = ConflictEngine(self.facts).scan() if len(self.facts) > 1 else []
                self._clusters = cluster_conflicts(conflicts)
            return self._clusters

    @property
    def casefile(self) -> dict:
        """The Case File for this snapshot (built once; snapshots are invalidated whenever documents change)."""
        self.clusters                                  # computed first (it takes the same lock)
        with self._lock:
            if self._casefile is None:
                from app.services.casefile import build_casefile
                self._casefile = build_casefile(self)
            return self._casefile

    def retriever(self, embedder: EmbeddingService | None, store: VectorStore | None) -> HybridRetriever:
        r = HybridRetriever.__new__(HybridRetriever)
        r.lex, r.chunks = self.lexical, self.chunks
        r.session_id, r.doc_ids = self.session_id, self.doc_ids
        r.embedder, r.store = embedder, store
        r._pos = {c.id: i for i, c in enumerate(self.chunks)}
        r._dense_used = False
        r.channels_used = []
        return r


def _build(db: Session, session_id: str, doc_ids: list[str] | None) -> Corpus:
    q = select(Document).where(Document.session_id == session_id, Document.status == "READY")
    if doc_ids:
        q = q.where(Document.id.in_(doc_ids))
    docs = {d.id: d for d in db.scalars(q.order_by(Document.uploaded_at))}
    info = {d.id: DocInfo(d.id, d.filename, d.doc_date, d.title, d.paged, d.ocr_conf) for d in docs.values()}
    chunks: list[Chunk] = []
    facts: list[Fact] = []
    if docs:
        ids = list(docs)
        for r in db.scalars(select(DocChunk).where(DocChunk.document_id.in_(ids)).order_by(DocChunk.document_id, DocChunk.chunk_index)):
            d = docs[r.document_id]
            chunks.append(Chunk(id=r.id, doc_id=r.document_id, doc_name=d.filename, idx=r.chunk_index, page=r.page_number, start=r.start_char,
                                end=r.end_char, section=r.section, text=r.text, ocr_conf=r.ocr_conf, paged=d.paged, doc_date=d.doc_date))
        for c in db.scalars(select(Claim).where(Claim.document_id.in_(ids)).order_by(Claim.document_id, Claim.id)):
            d = docs[c.document_id]
            facts.append(fact_from_dict(c.data, doc_id=d.id, doc_name=d.filename, doc_date=d.doc_date, doc_title=d.title, ocr_conf=None))
    # order documents by upload time so evidence/citation numbering is stable
    order = {d: i for i, d in enumerate(docs)}
    chunks.sort(key=lambda c: (order[c.doc_id], c.idx))
    chunk_by_id = {c.id: c for c in chunks}
    for f in facts:                                       # OCR confidence of the chunk the claim came from
        ch = chunk_by_id.get(f.chunk_id)
        if ch is not None:
            f.ocr_conf = ch.ocr_conf
    return Corpus(session_id=session_id, doc_ids=list(doc_ids) if doc_ids else None, docs=info, chunks=chunks, chunk_by_id=chunk_by_id,
                  facts=facts, lexical=LexicalIndex(chunks))


class CorpusCache:
    def __init__(self, max_items: int = 24):
        self._items: OrderedDict[tuple, Corpus] = OrderedDict()
        self._versions: dict[str, int] = {}
        self._lock = threading.RLock()
        self.max_items = max_items

    def bump(self, session_id: str) -> None:
        with self._lock:
            self._versions[session_id] = self._versions.get(session_id, 0) + 1
            for k in [k for k in self._items if k[0] == session_id]:
                self._items.pop(k, None)

    def get(self, db: Session, session_id: str, doc_ids: list[str] | None = None) -> Corpus:
        key = (session_id, tuple(sorted(doc_ids)) if doc_ids else None, self._versions.get(session_id, 0))
        with self._lock:
            hit = self._items.get(key)
            if hit is not None:
                self._items.move_to_end(key)
                return hit
        corpus = _build(db, session_id, doc_ids)
        with self._lock:
            self._items[key] = corpus
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return corpus

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


corpus_cache = CorpusCache()
