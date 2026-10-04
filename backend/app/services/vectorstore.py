"""Qdrant vector store: one collection with a dense vector and a sparse BM25 vector per chunk.

Server / Qdrant Cloud when QDRANT_URL is set, otherwise Qdrant's embedded local mode (same client API, no server needed).
Every query is filtered by `session_id` (tenant isolation) and optionally by `document_id`.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.domain import Chunk

log = logging.getLogger("docsherlock.qdrant")

DENSE = "dense"
SPARSE = "bm25"


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"docsherlock:{chunk_id}"))


@dataclass
class VectorHit:
    chunk_id: str
    score: float


class VectorStore:
    def __init__(self, dim: int = 384):
        self.dim = dim
        self.lock = threading.RLock()
        self.mode = "server" if settings.qdrant_url else "local"
        if settings.qdrant_url:
            self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=30)
        else:
            path = settings.qdrant_path or str(settings.data_dir / "qdrant")
            if path == ":memory:":
                self.client = QdrantClient(":memory:")
            else:
                settings.data_dir.mkdir(parents=True, exist_ok=True)
                self.client = QdrantClient(path=path)
        self.collection = settings.qdrant_collection
        self._ready = False

    # ---- collection ----------------------------------------------------------------------
    def ensure(self) -> None:
        if self._ready:
            return
        with self.lock:
            if self._ready:
                return
            existing = {c.name for c in self.client.get_collections().collections}
            if self.collection not in existing:
                self.client.create_collection(
                    self.collection,
                    vectors_config={DENSE: models.VectorParams(size=self.dim, distance=models.Distance.COSINE)},
                    sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
                )
                log.info("created Qdrant collection %s (%s mode)", self.collection, self.mode)
            if self.mode == "server":
                for field in ("session_id", "document_id"):
                    try:
                        self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)
                    except Exception:                      # already exists
                        pass
            self._ready = True

    def healthy(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception as exc:                          # pragma: no cover
            log.warning("qdrant unhealthy: %s", exc)
            return False

    # ---- writes --------------------------------------------------------------------------
    def upsert(self, session_id: str, chunks: list[Chunk], dense: list[list[float]] | None, sparse: list[tuple[list[int], list[float]]] | None) -> None:
        self.ensure()
        points = []
        for i, ch in enumerate(chunks):
            vector: dict = {}
            if dense is not None:
                vector[DENSE] = list(map(float, dense[i]))
            if sparse is not None and sparse[i][0]:
                vector[SPARSE] = models.SparseVector(indices=sparse[i][0], values=sparse[i][1])
            if not vector:
                continue
            points.append(models.PointStruct(id=point_id(ch.id), vector=vector, payload={
                "chunk_id": ch.id, "document_id": ch.doc_id, "session_id": session_id, "document_name": ch.doc_name,
                "page": ch.page, "section": ch.section}))
        with self.lock:
            for i in range(0, len(points), 64):
                self.client.upsert(self.collection, points=points[i:i + 64])

    def delete_document(self, document_id: str) -> None:
        self.ensure()
        with self.lock:
            self.client.delete(self.collection, points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])))

    def delete_session(self, session_id: str) -> None:
        self.ensure()
        with self.lock:
            self.client.delete(self.collection, points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id))])))

    def count(self, session_id: str | None = None) -> int:
        self.ensure()
        flt = models.Filter(must=[models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id))]) if session_id else None
        with self.lock:
            return self.client.count(self.collection, count_filter=flt, exact=True).count

    def count_document(self, document_id: str) -> int:
        self.ensure()
        flt = models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])
        with self.lock:
            return self.client.count(self.collection, count_filter=flt, exact=True).count

    # ---- reads ---------------------------------------------------------------------------
    @staticmethod
    def _filter(session_id: str, doc_ids: list[str] | None) -> models.Filter:
        must = [models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id))]
        if doc_ids:
            must.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=list(doc_ids))))
        return models.Filter(must=must)

    def search_dense(self, session_id: str, doc_ids: list[str] | None, vector, limit: int) -> list[VectorHit]:
        self.ensure()
        with self.lock:
            res = self.client.query_points(self.collection, query=list(map(float, vector)), using=DENSE, limit=limit,
                                           query_filter=self._filter(session_id, doc_ids), with_payload=["chunk_id"])
        return [VectorHit(p.payload["chunk_id"], float(p.score)) for p in res.points]

    def search_sparse(self, session_id: str, doc_ids: list[str] | None, indices: list[int], values: list[float], limit: int) -> list[VectorHit]:
        if not indices:
            return []
        self.ensure()
        with self.lock:
            res = self.client.query_points(self.collection, query=models.SparseVector(indices=indices, values=values), using=SPARSE, limit=limit,
                                           query_filter=self._filter(session_id, doc_ids), with_payload=["chunk_id"])
        return [VectorHit(p.payload["chunk_id"], float(p.score)) for p in res.points]


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


def reset_vector_store() -> None:
    """Drop the cached client (tests re-point the store at an in-memory instance)."""
    global _store
    _store = None
