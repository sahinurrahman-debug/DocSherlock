"""Hybrid retrieval: lexical (BM25 + char n-grams) + Qdrant dense + Qdrant sparse, fused with weighted RRF, then reranked by a
cross-encoder.

Besides a *ranking*, retrieval produces absolute *relevance signals* (term coverage, dense cosine) that feed the uncertainty
engine - a high rank in a corpus that does not really contain the answer must not look confident.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from app.core.config import settings
from app.domain import Chunk
from app.services.embeddings import EmbeddingService

if TYPE_CHECKING:                                    # the Qdrant client is only imported when semantic search is enabled
    from app.services.vectorstore import VectorStore
from app.utils.text import STOPWORDS, content_stems, question_stems, stem, tokenize

log = logging.getLogger("docsherlock.retrieval")

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


@dataclass
class Hit:
    chunk: Chunk
    rank_score: float
    bm25: float
    char_cos: float
    dense_cos: float | None
    coverage: float
    relevance: float
    rerank: float | None = None


def dense_norm(cos: float) -> float:
    """Map bge-small cosine similarity to 0..1 (unrelated text sits around 0.35-0.5)."""
    return float(min(1.0, max(0.0, (cos - 0.45) / 0.30)))


def relevance_score(coverage: float, char_cos: float, dense_cos: float | None) -> float:
    if dense_cos is not None:
        return 0.5 * coverage + 0.5 * dense_norm(dense_cos)
    return 0.8 * coverage + 0.2 * min(1.0, char_cos * 2.0)


class CharNgramIndex:
    """Character n-gram TF-IDF cosine (word-bounded 3-5 grams, sublinear tf, smooth idf, L2-normalised) - a drop-in, dependency-free
    equivalent of scikit-learn's TfidfVectorizer(analyzer="char_wb") for a few thousand passages. Saves ~130 MB of RAM."""

    def __init__(self, texts: list[str]):
        docs = [Counter(self._grams(t)) for t in texts]
        df: Counter = Counter()
        for c in docs:
            df.update(c.keys())
        n = len(texts)
        self.idf = {g: math.log((1 + n) / (1 + d)) + 1.0 for g, d in df.items()}
        self.n = n
        self.post: dict[str, list[tuple[int, float]]] = {}
        for i, c in enumerate(docs):
            w = {g: (1.0 + math.log(tf)) * self.idf[g] for g, tf in c.items()}
            norm = math.sqrt(sum(v * v for v in w.values())) or 1.0
            for g, v in w.items():
                self.post.setdefault(g, []).append((i, v / norm))

    @staticmethod
    def _grams(text: str, lo: int = 3, hi: int = 5):
        for word in " ".join(text.lower().split()).split():
            w = f" {word} "
            for k in range(lo, hi + 1):
                off = 0
                yield w[off:off + k]
                while off + k < len(w):
                    off += 1
                    yield w[off:off + k]
                if off == 0:
                    break

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(self.n)
        q = {g: (1.0 + math.log(tf)) * self.idf[g] for g, tf in Counter(self._grams(query)).items() if g in self.idf}
        norm = math.sqrt(sum(v * v for v in q.values()))
        if not norm:
            return out
        for g, v in q.items():
            qv = v / norm
            for i, w in self.post[g]:
                out[i] += qv * w
        return out


class LexicalIndex:
    """In-memory BM25 + char n-gram index over the chunks of one scope (a session and, optionally, a subset of documents)."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._tokens = [content_stems(c.index_text) for c in chunks]
        self._tf = [Counter(t) for t in self._tokens]
        self._df: Counter = Counter()
        for tf in self._tf:
            self._df.update(tf.keys())
        self._avgdl = (sum(len(t) for t in self._tokens) / len(self._tokens)) if self._tokens else 1.0
        self._chars = CharNgramIndex([c.index_text for c in chunks]) if chunks else None

    def idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def corpus_has(self, term: str) -> bool:
        return self._df.get(term, 0) > 0

    def term_known(self, term: str) -> bool:
        """Is the term (or a synonym / spelled-out acronym) present anywhere in the corpus?"""
        if self.corpus_has(term) or any(self.corpus_has(s) for s in _SYN_STEMS.get(term, ())):
            return True
        exp = _ACRO_STEMS.get(term)
        return bool(exp) and all(self.corpus_has(w) for w in exp)

    def query_terms(self, question: str) -> list[str]:
        terms = question_stems(question) or [stem(t) for t in tokenize(question)]
        seen, out = set(), []
        for t in terms:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def scores(self, question: str, terms: list[str]) -> tuple[np.ndarray, np.ndarray]:
        n = len(self.chunks)
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
        if self._chars is not None and terms:
            char = self._chars.scores(question)
        return bm, char

    def coverage(self, terms: list[str], i: int) -> float:
        total = sum(self.idf(t) for t in terms) or 1.0
        have = self._tf[i]
        return sum(self.idf(t) for t in terms if term_hit(t, have)) / total


def rrf(channels: list[tuple[list[int], float]], n: int, depth: int, c: int = 20) -> np.ndarray:
    """Weighted reciprocal-rank fusion of ranked index lists."""
    out = np.zeros(n)
    for ranked, weight in channels:
        for rank, idx in enumerate(ranked[:depth]):
            out[idx] += weight / (c + rank)
    return out


class HybridRetriever:
    """Retrieval for one scope. Exposes the lexical statistics the evidence/uncertainty layers need (idf, term_known ...)."""

    def __init__(self, chunks: list[Chunk], session_id: str, doc_ids: list[str] | None,
                 embedder: EmbeddingService | None, store: VectorStore | None):
        self.lex = LexicalIndex(chunks)
        self.chunks = chunks
        self.session_id, self.doc_ids = session_id, doc_ids
        self.embedder, self.store = embedder, store
        self._pos = {c.id: i for i, c in enumerate(chunks)}
        self._dense_used = False
        self.channels_used: list[str] = []

    # ---- lexical statistics (used by Analyzer) -------------------------------------------------
    def idf(self, term: str) -> float:
        return self.lex.idf(term)

    def corpus_has(self, term: str) -> bool:
        return self.lex.corpus_has(term)

    def term_known(self, term: str) -> bool:
        return self.lex.term_known(term)

    def query_terms(self, question: str) -> list[str]:
        return self.lex.query_terms(question)

    @property
    def dense(self):
        return self.embedder

    @property
    def dense_active(self) -> bool:
        return self._dense_used

    # ---- search --------------------------------------------------------------------------------
    def search(self, question: str, k: int | None = None) -> list[Hit]:
        if not self.chunks:
            return []
        k = k or settings.final_k
        terms = self.lex.query_terms(question)
        n = len(self.chunks)
        depth = max(settings.retrieve_k, k * 3)
        bm, char = self.lex.scores(question, terms)

        def ranked(scores: np.ndarray) -> list[int]:
            order = np.argsort(-scores)
            return [int(i) for i in order[:depth] if scores[i] > 0]

        channels = [(ranked(bm), 1.0), (ranked(char), 0.6)]
        self.channels_used = ["bm25", "char-ngrams"]
        dense_cos: dict[int, float] = {}
        self._dense_used = False
        if self.embedder is not None and self.store is not None and settings.dense_enabled:
            try:
                if self.embedder.ready:
                    qv = self.embedder.embed_query(question)
                    hits = self.store.search_dense(self.session_id, self.doc_ids, qv, limit=max(100, depth))
                    idx = [(self._pos[h.chunk_id], h.score) for h in hits if h.chunk_id in self._pos]
                    dense_cos = dict(idx)
                    if idx:
                        channels.append(([i for i, _ in idx[:depth]], 1.0))
                        self._dense_used = True
                        self.channels_used.append("qdrant-dense")
                if self.embedder.sparse_ready:
                    si, sv = self.embedder.sparse_query(question)
                    sh = self.store.search_sparse(self.session_id, self.doc_ids, si, sv, limit=depth)
                    sidx = [self._pos[h.chunk_id] for h in sh if h.chunk_id in self._pos]
                    if sidx:
                        channels.append((sidx, 0.6))
                        self.channels_used.append("qdrant-bm25")
            except Exception as exc:                       # vector store trouble must never take the answer path down
                log.warning("vector search failed, using lexical retrieval only: %s", exc)

        fused = rrf(channels, n, depth)
        order = [int(i) for i in np.argsort(-fused) if fused[i] > 0]
        cand = order[:max(settings.rerank_top, k)]
        if not cand:
            return []
        max_f = fused[cand[0]] or 1.0
        rank = {i: float(fused[i] / max_f) for i in cand}
        rerank: dict[int, float] = {}
        # reranking only changes *which* chunks reach the answer when there are more candidates than slots - skip it on small workspaces
        if settings.rerank_enabled and self.embedder is not None and self.embedder.rerank_ready and len(cand) > k:
            try:
                texts = [(self.chunks[i].index_text)[:900] for i in cand]
                scores = self.embedder.rerank(question, texts)
                lo, hi = min(scores), max(scores)
                span = (hi - lo) or 1.0
                for i, s in zip(cand, scores):
                    rerank[i] = float(s)
                    rank[i] = 0.5 * rank[i] + 0.5 * (s - lo) / span
                self.channels_used.append("cross-encoder")
            except Exception as exc:
                log.warning("rerank failed: %s", exc)
        top = sorted(cand, key=lambda i: -rank[i])[:k]
        peak = rank[top[0]] or 1.0

        hits: list[Hit] = []
        for i in top:
            cov = self.lex.coverage(terms, i)
            dcos = dense_cos.get(i)
            hits.append(Hit(self.chunks[i], float(rank[i] / peak), float(bm[i]), float(char[i]), dcos, cov,
                            relevance_score(cov, float(char[i]), dcos), rerank.get(i)))
        return hits
