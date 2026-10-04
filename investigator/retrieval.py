"""Hybrid retrieval: BM25 (stemmed) + char n-gram TF-IDF + optional dense embeddings, fused with weighted RRF.

Besides a *ranking*, retrieval produces absolute *relevance signals* (term coverage, dense cosine) that feed the
confidence model - a high rank in a corpus that does not really contain the answer must not look confident.
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections import Counter
from dataclasses import dataclass

import numpy as np

from . import config
from .models import Chunk
from .textutil import STOPWORDS, content_stems, question_stems, stem, tokenize

log = logging.getLogger("docinv.retrieval")

_SYNONYMS = {
    "fire": ["terminate", "dismiss"], "cancel": ["terminate"], "terminate": ["cancel"], "cost": ["price", "fee", "charge", "amount"],
    "price": ["cost", "fee"], "staff": ["employee", "headcount"], "headcount": ["employee", "staff"], "employee": ["staff", "headcount"],
    "salary": ["pay", "compensation"], "boss": ["manager"], "begin": ["start", "commence"],
    "start": ["commence", "begin", "effective"], "end": ["expire", "terminate", "expiry"], "expire": ["end", "expiry"],
    "fee": ["charge", "cost", "price"], "penalty": ["fine", "liquidated", "damage"], "late": ["delay", "overdue"],
    "bill": ["invoice"], "invoice": ["bill"], "refund": ["reimburse", "reimbursement"], "breach": ["violation", "default"],
    "leader": ["head", "director", "chief"], "buy": ["purchase"], "purchase": ["buy", "procurement"], "yearly": ["annual"],
    "annual": ["yearly"], "rule": ["policy"], "policy": ["rule", "guideline"], "money": ["amount", "payment", "fund"],
    "worker": ["employee"], "due": ["deadline"], "deadline": ["due", "completion"], "finish": ["complete", "completion", "end"], "complete": ["finish", "completion", "deadline"], "completion": ["complete", "finish", "deadline"], "payment": ["payable", "pay"], "payable": ["payment", "pay"], "rotate": ["change", "rotation", "expire"], "rotation": ["change", "rotate"],
}
# Acronyms documents often spell out. Unlike synonyms, ALL expansion words must co-occur to count as a match.
_ACRONYMS = {
    "mfa": ["multi", "factor", "authentication"], "2fa": ["two", "factor", "authentication"], "sla": ["service", "level", "agreement"],
    "nda": ["non-disclosure", "agreement"], "kpi": ["key", "performance", "indicator"], "ceo": ["chief", "executive", "officer"],
    "cfo": ["chief", "financial", "officer"], "cto": ["chief", "technology", "officer"], "hr": ["human", "resources"],
    "gdpr": ["data", "protection", "regulation"], "pto": ["paid", "time", "off"], "sow": ["statement", "of", "work"],
}
_SYN_STEMS = {stem(k): [stem(v) for v in vs] for k, vs in _SYNONYMS.items()}
_ACRO_STEMS = {k: [stem(w) for w in tokenize(" ".join(vs)) if w not in STOPWORDS] for k, vs in _ACRONYMS.items()}


def term_hit(t: str, stems_) -> bool:
    """Does the stem set satisfy query term `t` (directly, via a synonym, or via a fully spelled-out acronym)?"""
    if t in stems_ or any(s in stems_ for s in _SYN_STEMS.get(t, ())):
        return True
    exp = _ACRO_STEMS.get(t)
    return bool(exp) and all(w in stems_ for w in exp)



class DenseEmbedder:
    """Lazy fastembed wrapper. Loads in a background thread so the app starts instantly."""

    def __init__(self):
        self.model = None
        self.error: str | None = None
        self.loading = False
        self._lock = threading.Lock()
        self.enabled = config.DENSE not in {"0", "off", "false", "no"}

    @property
    def ready(self) -> bool:
        return self.model is not None

    def warmup(self, blocking: bool = False, on_ready=None) -> None:
        if not self.enabled or self.model is not None or self.loading:
            return
        self.loading = True

        def load():
            try:
                from fastembed import TextEmbedding  # type: ignore
                m = TextEmbedding(config.DENSE_MODEL)
                list(m.embed(["warm up"]))
                self.model = m
                log.info("dense embedder ready: %s", config.DENSE_MODEL)
                if on_ready:
                    on_ready()
            except Exception as exc:  # pragma: no cover - environment dependent
                self.error = f"{exc.__class__.__name__}: {exc}"
                log.warning("dense embeddings unavailable: %s", self.error)
            finally:
                self.loading = False

        if blocking:
            load()
        else:
            threading.Thread(target=load, daemon=True, name="dense-load").start()

    def embed_docs(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vecs = list(self.model.embed(texts, batch_size=16))
        return _unit(np.array(vecs, dtype=np.float32))

    def embed_query(self, q: str) -> np.ndarray:
        with self._lock:
            try:
                v = next(iter(self.model.query_embed(q)))
            except AttributeError:
                v = next(iter(self.model.embed([q])))
        return _unit(np.array(v, dtype=np.float32)[None, :])[0]


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    n[n == 0] = 1
    return m / n


@dataclass
class Hit:
    chunk: Chunk
    rank_score: float
    bm25: float
    char_cos: float
    dense_cos: float | None
    coverage: float
    relevance: float


class Retriever:
    def __init__(self, dense: DenseEmbedder | None = None):
        self.dense = dense
        self.chunks: list[Chunk] = []
        self.emb_cache: dict[str, np.ndarray] = {}
        self._tokens: list[list[str]] = []
        self._tf: list[Counter] = []
        self._df: Counter = Counter()
        self._avgdl = 1.0
        self._vec = None
        self._mat = None
        self._emb: np.ndarray | None = None

    # -- indexing -----------------------------------------------------------------------------
    @staticmethod
    def text_key(chunk: Chunk) -> str:
        return hashlib.sha1(chunk.index_text.encode("utf-8")).hexdigest()

    def build(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._tokens = [content_stems(c.index_text) for c in chunks]
        self._tf = [Counter(t) for t in self._tokens]
        self._df = Counter()
        for tf in self._tf:
            self._df.update(tf.keys())
        self._avgdl = (sum(len(t) for t in self._tokens) / len(self._tokens)) if self._tokens else 1.0
        self._vec = self._mat = None
        if chunks:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1, lowercase=True)
            self._mat = self._vec.fit_transform([c.index_text for c in chunks])
        self.refresh_dense()

    def refresh_dense(self) -> int:
        """Embed any chunks lacking cached vectors (if the model is ready). Returns number embedded."""
        self._emb = None
        if not (self.dense and self.dense.ready and self.chunks):
            return 0
        keys = [self.text_key(c) for c in self.chunks]
        missing = [i for i, k in enumerate(keys) if k not in self.emb_cache]
        if missing:
            vecs = self.dense.embed_docs([self.chunks[i].index_text for i in missing])
            for i, v in zip(missing, vecs):
                self.emb_cache[keys[i]] = v
        self._emb = np.stack([self.emb_cache[k] for k in keys])
        return len(missing)

    @property
    def dense_active(self) -> bool:
        return self._emb is not None

    # -- statistics ---------------------------------------------------------------------------
    def idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def df(self, term: str) -> int:
        return self._df.get(term, 0)

    def corpus_has(self, term: str) -> bool:
        return self._df.get(term, 0) > 0

    def term_known(self, term: str) -> bool:
        """Is the term (or a synonym / spelled-out acronym) present anywhere in the corpus?"""
        if self.corpus_has(term) or any(self.corpus_has(s) for s in _SYN_STEMS.get(term, ())):
            return True
        exp = _ACRO_STEMS.get(term)
        return bool(exp) and all(self.corpus_has(w) for w in exp)

    # -- search -------------------------------------------------------------------------------
    def query_terms(self, question: str) -> list[str]:
        terms = question_stems(question)
        if not terms:
            terms = [stem(t) for t in tokenize(question)]
        seen, out = set(), []
        for t in terms:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def search(self, question: str, k: int = 8) -> list[Hit]:
        if not self.chunks:
            return []
        terms = self.query_terms(question)
        n = len(self.chunks)

        # BM25 with down-weighted synonym expansion
        weighted: dict[str, float] = {t: 1.0 for t in terms}
        for t in terms:
            for s in _SYN_STEMS.get(t, []) + _ACRO_STEMS.get(t, []):
                weighted.setdefault(s, 0.45)
        k1, b = 1.4, 0.75
        bm = np.zeros(n)
        for i, tf in enumerate(self._tf):
            dl = len(self._tokens[i]) or 1
            s = 0.0
            for t, w in weighted.items():
                f = tf.get(t)
                if f:
                    s += w * self.idf(t) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / self._avgdl))
            bm[i] = s

        char = np.zeros(n)
        if self._vec is not None and terms:
            q = self._vec.transform([question])
            char = (self._mat @ q.T).toarray().ravel()

        dense = None
        if self._emb is not None:
            qv = self.dense.embed_query(question)
            dense = self._emb @ qv

        rrf = np.zeros(n)
        channels = [(bm, 1.0), (char, 0.6)] + ([(dense, 1.0)] if dense is not None else [])
        for scores, weight in channels:
            order = np.argsort(-scores)
            for rank, idx in enumerate(order[: max(50, k * 4)]):
                if scores[idx] <= 0:
                    break
                rrf[idx] += weight / (20 + rank)
        top = np.argsort(-rrf)[:k]
        max_rrf = rrf[top[0]] if len(top) and rrf[top[0]] > 0 else 1.0

        total_idf = sum(self.idf(t) for t in terms) or 1.0
        hits: list[Hit] = []
        for i in top:
            if rrf[i] <= 0:
                continue
            have = self._tf[i]
            matched = 0.0
            for t in terms:
                if term_hit(t, have):
                    matched += self.idf(t)
            cov = matched / total_idf
            dcos = float(dense[i]) if dense is not None else None
            rel = relevance_score(cov, float(char[i]), dcos)
            hits.append(Hit(self.chunks[i], float(rrf[i] / max_rrf), float(bm[i]), float(char[i]), dcos, cov, rel))
        return hits


def dense_norm(cos: float) -> float:
    """Map bge-small cosine similarity to 0..1 (unrelated text sits around 0.35-0.5)."""
    return float(min(1.0, max(0.0, (cos - 0.45) / 0.30)))


def relevance_score(coverage: float, char_cos: float, dense_cos: float | None) -> float:
    if dense_cos is not None:
        return 0.5 * coverage + 0.5 * dense_norm(dense_cos)
    return 0.8 * coverage + 0.2 * min(1.0, char_cos * 2.0)
