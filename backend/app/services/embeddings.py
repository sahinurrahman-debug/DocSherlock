"""FastEmbed models, run locally: dense embeddings, sparse BM25 vectors and a cross-encoder reranker.

Models load lazily in a background thread so the API starts instantly; until they are ready the system degrades gracefully
(lexical retrieval only, no reranking) and `/health` reports it.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from typing import Callable

import numpy as np

from app.core.config import settings

log = logging.getLogger("docsherlock.embeddings")


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    n[n == 0] = 1
    return m / n


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
        return {"dense": self.dense_m.status(), "sparse": self.sparse_m.status(), "reranker": self.rerank_m.status()}

    # ---- dense ---------------------------------------------------------------------------
    def embed_docs(self, texts: list[str]) -> np.ndarray:
        with self.dense_m.lock:
            vecs = list(self.dense_m.model.embed(texts, batch_size=16))
        return _unit(np.array(vecs, dtype=np.float32))

    def embed_query(self, q: str) -> np.ndarray:
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
        return hashlib.sha1(f"{settings.embedding_model}|{text}".encode("utf-8")).hexdigest()


_service: EmbeddingService | None = None


def get_embeddings() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
