"""Qdrant vector store: one collection with a dense vector and a sparse BM25 vector per chunk.

Two interchangeable backends behind one interface (requests are plain JSON bodies, the same ones the REST API takes):
  * server / Qdrant Cloud (QDRANT_URL set): a thin httpx client - the official `qdrant-client` (gRPC + pydantic models, ~90 MB of RAM) is never imported,
    which is what lets a 512 MB host run it;
  * embedded local mode (no QDRANT_URL): the official client in-process, no server needed. It validates every body against the official models.
Every query is filtered by `session_id` (tenant isolation) and optionally by `document_id`.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.domain import Chunk

log = logging.getLogger("docsherlock.qdrant")

DENSE = "dense"
SPARSE = "bm25"

_http_transport: httpx.BaseTransport | None = None            # tests inject a fake Qdrant server here


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"docsherlock:{chunk_id}"))


@dataclass
class VectorHit:
    chunk_id: str
    score: float


def _match(key: str, value) -> dict:
    return {"key": key, "match": {"any": list(value)} if isinstance(value, (list, tuple)) else {"value": value}}


def _filter(**conds) -> dict:
    return {"must": [_match(k, v) for k, v in conds.items() if v is not None]}


# ---- backends ---------------------------------------------------------------------------------
class _RestBackend:
    mode = "server"

    def __init__(self, collection: str):
        self.collection = collection
        headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
        self.http = httpx.Client(base_url=settings.qdrant_url.rstrip("/"), headers=headers, timeout=30, transport=_http_transport)

    def _call(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        r = self.http.request(method, path, json=body, params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"Qdrant {method} {path} -> HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("result") or {}

    def collections(self) -> set[str]:
        return {c["name"] for c in self._call("GET", "/collections").get("collections", [])}

    def create(self, body: dict) -> None:
        self._call("PUT", f"/collections/{self.collection}", body)

    def index(self, field: str) -> None:
        self._call("PUT", f"/collections/{self.collection}/index", {"field_name": field, "field_schema": "keyword"}, {"wait": "true"})

    def upsert(self, points: list[dict]) -> None:
        self._call("PUT", f"/collections/{self.collection}/points", {"points": points}, {"wait": "true"})

    def delete(self, flt: dict) -> None:
        self._call("POST", f"/collections/{self.collection}/points/delete", {"filter": flt}, {"wait": "true"})

    def count(self, flt: dict | None) -> int:
        body: dict = {"exact": True}
        if flt:
            body["filter"] = flt
        return int(self._call("POST", f"/collections/{self.collection}/points/count", body).get("count", 0))

    def query(self, query, using: str, flt: dict, limit: int) -> list[VectorHit]:
        res = self._call("POST", f"/collections/{self.collection}/points/query",
                         {"query": query, "using": using, "limit": limit, "filter": flt, "with_payload": ["chunk_id"]})
        return [VectorHit(p["payload"]["chunk_id"], float(p["score"])) for p in res.get("points", [])]


class _LocalBackend:
    mode = "local"

    def __init__(self, collection: str):
        from qdrant_client import QdrantClient               # lazy: only the embedded mode needs the official client
        self.collection = collection
        path = settings.qdrant_path or str(settings.data_dir / "qdrant")
        if path == ":memory:":
            self.client = QdrantClient(":memory:")
        else:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=path)

    def collections(self) -> set[str]:
        return {c.name for c in self.client.get_collections().collections}

    def create(self, body: dict) -> None:
        from qdrant_client import models
        self.client.create_collection(
            self.collection,
            vectors_config={k: models.VectorParams.model_validate(v) for k, v in body["vectors"].items()},
            sparse_vectors_config={k: models.SparseVectorParams.model_validate(v) for k, v in body["sparse_vectors"].items()})

    def index(self, field: str) -> None:                       # payload indexes only matter for servers
        pass

    def upsert(self, points: list[dict]) -> None:
        from qdrant_client import models
        self.client.upsert(self.collection, points=[models.PointStruct.model_validate(p) for p in points])

    def delete(self, flt: dict) -> None:
        from qdrant_client import models
        self.client.delete(self.collection, points_selector=models.FilterSelector(filter=models.Filter.model_validate(flt)))

    def count(self, flt: dict | None) -> int:
        from qdrant_client import models
        f = models.Filter.model_validate(flt) if flt else None
        return self.client.count(self.collection, count_filter=f, exact=True).count

    def query(self, query, using: str, flt: dict, limit: int) -> list[VectorHit]:
        from qdrant_client import models
        q = models.SparseVector.model_validate(query) if isinstance(query, dict) else query
        res = self.client.query_points(self.collection, query=q, using=using, limit=limit,
                                       query_filter=models.Filter.model_validate(flt), with_payload=["chunk_id"])
        return [VectorHit(p.payload["chunk_id"], float(p.score)) for p in res.points]


class VectorStore:
    def __init__(self, dim: int | None = None):
        self.dim = dim or settings.embedding_dim
        self.lock = threading.RLock()
        self.collection = settings.collection_name
        self.backend = _RestBackend(self.collection) if settings.qdrant_url else _LocalBackend(self.collection)
        self.mode = self.backend.mode
        self._ready = False

    # ---- collection ----------------------------------------------------------------------
    def ensure(self) -> None:
        if self._ready:
            return
        with self.lock:
            if self._ready:
                return
            if self.collection not in self.backend.collections():
                self.backend.create({"vectors": {DENSE: {"size": self.dim, "distance": "Cosine"}},
                                     "sparse_vectors": {SPARSE: {"modifier": "idf"}}})
                log.info("created Qdrant collection %s (%s mode)", self.collection, self.mode)
            if self.mode == "server":
                for field in ("session_id", "document_id"):
                    try:
                        self.backend.index(field)
                    except Exception:                      # already exists
                        pass
            self._ready = True

    def healthy(self) -> bool:
        try:
            self.backend.collections()
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
                vector[DENSE] = [float(x) for x in dense[i]]
            if sparse is not None and sparse[i][0]:
                vector[SPARSE] = {"indices": [int(x) for x in sparse[i][0]], "values": [float(x) for x in sparse[i][1]]}
            if not vector:
                continue
            points.append({"id": point_id(ch.id), "vector": vector, "payload": {
                "chunk_id": ch.id, "document_id": ch.doc_id, "session_id": session_id, "document_name": ch.doc_name,
                "page": ch.page, "section": ch.section}})
        with self.lock:
            for i in range(0, len(points), 64):
                self.backend.upsert(points[i:i + 64])

    def delete_document(self, document_id: str) -> None:
        self.ensure()
        with self.lock:
            self.backend.delete(_filter(document_id=document_id))

    def delete_session(self, session_id: str) -> None:
        self.ensure()
        with self.lock:
            self.backend.delete(_filter(session_id=session_id))

    def count(self, session_id: str | None = None) -> int:
        self.ensure()
        with self.lock:
            return self.backend.count(_filter(session_id=session_id) if session_id else None)

    def count_document(self, document_id: str) -> int:
        self.ensure()
        with self.lock:
            return self.backend.count(_filter(document_id=document_id))

    # ---- reads ---------------------------------------------------------------------------
    def search_dense(self, session_id: str, doc_ids: list[str] | None, vector, limit: int) -> list[VectorHit]:
        self.ensure()
        flt = _filter(session_id=session_id, document_id=list(doc_ids) if doc_ids else None)
        with self.lock:
            return self.backend.query([float(x) for x in vector], DENSE, flt, limit)

    def search_sparse(self, session_id: str, doc_ids: list[str] | None, indices: list[int], values: list[float], limit: int) -> list[VectorHit]:
        if not indices:
            return []
        self.ensure()
        flt = _filter(session_id=session_id, document_id=list(doc_ids) if doc_ids else None)
        q = {"indices": [int(x) for x in indices], "values": [float(x) for x in values]}
        with self.lock:
            return self.backend.query(q, SPARSE, flt, limit)


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
