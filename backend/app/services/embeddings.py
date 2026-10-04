"""Embedding models: dense embeddings (local FastEmbed *or* a hosted API), sparse BM25 vectors and a cross-encoder reranker.

Models load lazily in a background thread so the API starts instantly; until they are ready the system degrades gracefully
(lexical retrieval only, no reranking) and `/health` reports it.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Callable

import httpx
import numpy as np

from app.core.config import settings

log = logging.getLogger("docsherlock.embeddings")


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    n[n == 0] = 1
    return m / n


class EmbeddingAPIError(RuntimeError):
    pass


_http_transport: httpx.BaseTransport | None = None            # tests inject a fake server here


class ApiEmbedder:
    """Dense embeddings from a hosted OpenAI-style endpoint: POST {"model", "input": [...]} -> {"data": [{"index", "embedding"}]}.

    Jina's endpoint additionally takes a `task` (retrieval.passage / retrieval.query), which is sent automatically for jina.ai URLs.
    Nothing is loaded locally, so the process stays small. 429 / 5xx responses are retried with back-off.
    """

    def __init__(self):
        self.url = settings.embedding_api_url
        self.dim = settings.embedding_dim
        self.jina = "jina.ai" in self.url
        headers = {"Authorization": f"Bearer {settings.embedding_api_key}"} if settings.embedding_api_key else {}
        self.client = httpx.Client(timeout=settings.embedding_api_timeout_s, headers=headers, transport=_http_transport)

    def _request(self, texts: list[str], kind: str) -> list[list[float]]:
        body: dict = {"model": settings.embedding_model, "input": texts}
        if settings.embedding_api_dimensions:
            body["dimensions"] = self.dim
        if self.jina:
            body["task"] = "retrieval.query" if kind == "query" else "retrieval.passage"
        last = "no response"
        for attempt in range(4):
            try:
                r = self.client.post(self.url, json=body)
            except httpx.TransportError as exc:
                last = f"{exc.__class__.__name__}"
                time.sleep(min(2 ** attempt, 8))
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                try:
                    wait = float(r.headers.get("retry-after", ""))
                except ValueError:
                    wait = 2.0 ** attempt
                time.sleep(min(wait, 8.0))
                continue
            if r.status_code >= 400:
                raise EmbeddingAPIError(f"embedding API answered HTTP {r.status_code}: {r.text[:200]}")
            data = sorted(r.json().get("data", []), key=lambda d: d.get("index", 0))
            vecs = [d["embedding"] for d in data]
            if len(vecs) != len(texts):
                raise EmbeddingAPIError(f"embedding API returned {len(vecs)} vectors for {len(texts)} texts")
            if vecs and len(vecs[0]) != self.dim:
                raise EmbeddingAPIError(f"embedding API returned {len(vecs[0])}-dimensional vectors but EMBEDDING_DIM={self.dim}")
            return vecs
        raise EmbeddingAPIError(f"embedding API unavailable ({last}) after retries")

    def embed(self, texts: list[str], kind: str = "doc") -> list[list[float]]:
        out: list[list[float]] = []
        step = max(1, settings.embedding_api_batch)
        for i in range(0, len(texts), step):
            out.extend(self._request(texts[i:i + step], kind))
        return out


class _Lazy:
    """A model that is loaded once, off the request path."""

    def __init__(self, name: str, loader: Callable[[], object], enabled: bool = True):
        self.name, self._loader, self.enabled = name, loader, enabled
        self.model = None
        self.error: str | None = None
        self.loading = False
        self.lock = threading.Lock()                # FastEmbed sessions are not guaranteed thread safe
        self._load_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.model is not None

    def load(self) -> None:
        with self._load_lock:
            if self.model is not None or not self.enabled:
                return
            self.loading = True
            try:
                self.model = self._loader()
                log.info("model ready: %s", self.name)
            except Exception as exc:                  # pragma: no cover - environment dependent
                self.error = f"{exc.__class__.__name__}: {exc}"
                log.warning("model %s unavailable: %s", self.name, self.error)
            finally:
                self.loading = False

    def status(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "ready": self.ready, "loading": self.loading, "error": self.error}


class EmbeddingService:
    def __init__(self):
        def load_dense():
            if settings.api_embeddings:
                return ApiEmbedder()                  # no model to load; errors surface per request and are retried by the back-fill
            from fastembed import TextEmbedding
            m = TextEmbedding(settings.embedding_model)
            list(m.embed(["warm up"]))
            return m

        def load_sparse():
            from fastembed import SparseTextEmbedding
            return SparseTextEmbedding(settings.sparse_model)

        def load_rerank():
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            m = TextCrossEncoder(settings.reranker_model)
            list(m.rerank("warm up", ["warm up"]))
            return m

        self.dense_m = _Lazy(settings.embedding_model, load_dense, settings.dense_enabled)
        self.sparse_m = _Lazy(settings.sparse_model, load_sparse, settings.dense_enabled)
        self.rerank_m = _Lazy(settings.reranker_model, load_rerank, settings.dense_enabled and settings.rerank_enabled)
        self._thread: threading.Thread | None = None
        self.on_ready: list[Callable[[], None]] = []

    # ---- lifecycle -----------------------------------------------------------------------
    def warmup(self, blocking: bool = False) -> None:
        def run():
            for m in (self.dense_m, self.sparse_m, self.rerank_m):
                m.load()
            for cb in self.on_ready:
                try:
                    cb()
                except Exception:                      # pragma: no cover
                    log.exception("on_ready callback failed")

        if blocking:
            run()
        elif self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=run, daemon=True, name="model-warmup")
            self._thread.start()

    @property
    def ready(self) -> bool:                           # dense embeddings available
        return self.dense_m.ready

    @property
    def sparse_ready(self) -> bool:
        return self.sparse_m.ready

    @property
    def rerank_ready(self) -> bool:
        return self.rerank_m.ready

    @property
    def loading(self) -> bool:
        return self.dense_m.loading or self.sparse_m.loading or self.rerank_m.loading

    def status(self) -> dict:
        return {"dense": self.dense_m.status() | {"source": "api" if settings.api_embeddings else "local"}, "sparse": self.sparse_m.status(),
                "reranker": self.rerank_m.status()}

    # ---- dense ---------------------------------------------------------------------------
    def embed_docs(self, texts: list[str]) -> np.ndarray:
        if isinstance(self.dense_m.model, ApiEmbedder):
            return _unit(np.array(self.dense_m.model.embed(texts, "doc"), dtype=np.float32))
        with self.dense_m.lock:
            vecs = list(self.dense_m.model.embed(texts, batch_size=16))
        return _unit(np.array(vecs, dtype=np.float32))

    def embed_query(self, q: str) -> np.ndarray:
        if isinstance(self.dense_m.model, ApiEmbedder):
            return _unit(np.array(self.dense_m.model.embed([q], "query"), dtype=np.float32))[0]
        with self.dense_m.lock:
            try:
                v = next(iter(self.dense_m.model.query_embed(q)))
            except AttributeError:
                v = next(iter(self.dense_m.model.embed([q])))
        return _unit(np.array(v, dtype=np.float32)[None, :])[0]

    # ---- sparse (BM25 term weights, scored by Qdrant) ----------------------------------------
    def sparse_docs(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        with self.sparse_m.lock:
            out = list(self.sparse_m.model.embed(texts))
        return [(e.indices.tolist(), e.values.tolist()) for e in out]

    def sparse_query(self, q: str) -> tuple[list[int], list[float]]:
        with self.sparse_m.lock:
            e = next(iter(self.sparse_m.model.query_embed(q)))
        return e.indices.tolist(), e.values.tolist()

    # ---- reranker --------------------------------------------------------------------------
    def rerank(self, query: str, texts: list[str]) -> list[float]:
        with self.rerank_m.lock:
            return [float(s) for s in self.rerank_m.model.rerank(query, texts)]

    # ---- cache key -------------------------------------------------------------------------
    @staticmethod
    def cache_key(text: str) -> str:
        tag = f"api|{settings.embedding_model}|{settings.embedding_dim}" if settings.api_embeddings else settings.embedding_model
        return hashlib.sha1(f"{tag}|{text}".encode("utf-8")).hexdigest()


_service: EmbeddingService | None = None


def get_embeddings() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
