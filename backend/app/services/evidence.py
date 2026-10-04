"""Question analysis, evidence selection and conflict relevance (shared by the LLM and the rule-based engines)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain import Chunk, Quantity
from app.services.facts import extract_quantities
from app.services.retriever import Hit, HybridRetriever as Retriever, dense_norm, term_hit
from app.utils.text import STOPWORDS, QUESTION_FILLER, content_stems, normalize_ws, split_sentences, question_stems, stem, tokenize

_MONTH_RE = re.compile(r"\b(january|february|march|april|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b")


# ---------------------------------------------------------------------------------------------
# Question analysis
# ---------------------------------------------------------------------------------------------
@dataclass
class QuestionInfo:
    text: str
    terms: list[str]
    qtype: str                      # quantity | date | who | yesno | generic
    wants: set[str] = field(default_factory=set)
    strict: bool = False            # wants came from an explicit "how many/when ..." pattern (hard filter for conflicts)
    periods: set[str] = field(default_factory=set)   # months / years the question is scoped to


_PRONOUN_START = re.compile(r"^\s*(?:and\s+|what about\s+|how about\s+|why\s+|so\s+)?(?:it|its|that|this|they|them|those|these|he|she|his|her|the same|which one|which)\b", re.I)


def analyse_question(text: str, retriever: Retriever) -> QuestionInfo:
    t = text.lower()
    terms = retriever.query_terms(text)
    wants: set[str] = set()
    qtype = "generic"
    strict = False
    if re.search(r"\bhow (?:many|much|long|often|big|large|old)\b", t):
        qtype, strict = "quantity", True
        if re.search(r"\bhow many\b", t):
            wants = {"number", "duration"} if re.search(r"\b(?:days?|weeks?|months?|years?|hours?|minutes?)\b", t) else {"number"}
        elif re.search(r"\bhow (?:long|often)\b", t):
            wants = {"duration"}
        else:
            wants = {"money", "number", "percent"}
    elif re.search(r"\bwhen\b|\bwhat date\b|\bwhich date\b|\bby when\b|\bdate of\b", t):
        qtype, strict, wants = "date", True, {"date"}
    elif re.match(r"^\s*who\b", t):
        qtype = "who"
    elif re.match(r"^\s*(?:is|are|does|do|did|can|could|will|was|were|has|have|should|must|may)\b", t):
        qtype = "yesno"
    if not wants:                    # soft hints from vocabulary (ranking bonus only)
        if re.search(r"\b(?:budget|cost|price|fee|salary|revenue|amount|spend|liability|cap|worth|payment amount)\b", t):
            wants, qtype = {"money"}, "quantity"
        elif re.search(r"\b(?:percent|percentage|rate|margin|turnover)\b", t):
            wants, qtype = {"percent", "money"}, "quantity"
        elif re.search(r"\b(?:period|notice|duration|deadline|terms?)\b", t):
            wants = {"duration"}
        elif re.search(r"\b(?:headcount|employees|number of)\b", t):
            wants = {"number"}
    periods = set(_MONTH_RE.findall(t)) | set(re.findall(r"\b((?:19|20)\d{2})\b", t))
    return QuestionInfo(text=text, terms=terms, qtype=qtype, wants=wants, strict=strict, periods=periods)


def contextualize(question: str, history: list[dict] | None, retriever: Retriever) -> str:
    """Resolve terse follow-ups ("and for the amendment?") by borrowing topical terms from the previous question."""
    if not history:
        return question
    prev = next((h.get("question") for h in reversed(history) if h.get("question")), None)
    if not prev:
        return question
    terms = question_stems(question)
    if len(terms) <= 1 or (_PRONOUN_START.match(question) and len(terms) <= 2):
        return f"{prev.rstrip('?')} - {question}"
    return question


# ---------------------------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------------------------
@dataclass
class Evidence:
    chunk: Chunk
    sent_start: int                 # offsets inside the chunk text
    sent_end: int
    text: str
    score: float
    cov: float
    quantities: list[Quantity]
    hit: Hit

    @property
    def page_start(self) -> int:
        return self.chunk.start + self.sent_start

    @property
    def page_end(self) -> int:
        return self.chunk.start + self.sent_end


@dataclass
class Context:
    question: str
    effective_question: str
    info: QuestionInfo
    hits: list[Hit]
    evidence: list[Evidence]
    conflicts: list[dict]                   # conflict clusters relevant to this question (see conflicts.cluster_conflicts)
    missing_terms: list[str]
    dense_active: bool
    best_cov: float = 0.0
    union_cov: float = 0.0
    conflict_cov: float = 0.0
    n_docs_corpus: int = 0
    hit_chunks: dict[str, Chunk] = field(default_factory=dict)


def _ordered_stems(text: str, drop=frozenset()) -> list[str]:
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS and t not in drop and len(t) > 1]


def _bigrams(seq: list[str]) -> set[tuple[str, str]]:
    return set(zip(seq, seq[1:]))


def _has_wanted(quantities: list[Quantity], wants: set[str]) -> bool:
    return any(q.kind in wants for q in quantities)


class Analyzer:
    def __init__(self, retriever: Retriever, chunk_lookup: dict[str, Chunk], clusters: list[dict], n_docs: int):
        self.r = retriever
        self.chunks = chunk_lookup
        self.clusters = clusters
        self.n_docs = n_docs

    # -- coverage -----------------------------------------------------------------------------
    def coverage(self, terms: list[str], stems_: set[str], heading: set[str] | None = None, title: set[str] | None = None,
                 known_only: bool = False) -> float:
        if known_only:
            terms = [t for t in terms if self.r.term_known(t)]
        terms = [t for t in terms if not (t in self.GENERIC and not self.r.term_known(t))]
        if not terms:
            return 0.0
        total = sum(self.r.idf(t) for t in terms) or 1.0
        got = 0.0
        for t in terms:
            idf = self.r.idf(t)
            if term_hit(t, stems_):
                got += idf
            elif heading and term_hit(t, heading):
                got += 0.6 * idf
            elif title and t in title:
                got += 0.4 * idf
        return got / total

    GENERIC = frozenset({"period", "term", "amount", "number", "total", "date", "time", "rate", "value", "level", "kind", "type", "part",
                         "way", "thing", "reason", "name"})

    def anchors(self, terms: list[str]) -> list[str]:
        """The rarest meaningful question terms - an answer that ignores them is probably about something else."""
        known = [t for t in terms if self.r.term_known(t) and t not in self.GENERIC]
        if not known:
            return []
        mx = max(self.r.idf(t) for t in known)
        return [t for t in sorted(known, key=lambda t: -self.r.idf(t)) if self.r.idf(t) >= 0.75 * mx][:2]

    @staticmethod
    def covers_anchor(anchors: list[str], *stem_sets: set[str]) -> bool:
        if not anchors:
            return True
        return any(term_hit(t, ss) for t in anchors for ss in stem_sets if ss)

    # -- main ---------------------------------------------------------------------------------
    def build(self, question: str, effective: str, k: int = 8) -> Context:
        info = analyse_question(effective, self.r)
        hits = self.r.search(effective, k=k)
        evidence = self._select_evidence(info, hits)
        missing = [t for t in info.terms if len(t) > 2 and t not in self.GENERIC and not self.r.term_known(t)]
        ctx = Context(question=question, effective_question=effective, info=info, hits=hits, evidence=evidence, conflicts=[],
                      missing_terms=missing, dense_active=self.r.dense_active, n_docs_corpus=self.n_docs,
                      hit_chunks={h.chunk.id: h.chunk for h in hits})
        if evidence:
            ctx.best_cov = evidence[0].cov
            union: set[str] = set()
            for e in evidence[:3]:
                union |= set(content_stems(e.text)) | set(content_stems(e.chunk.section))
            ctx.union_cov = self.coverage(info.terms, union)
        ctx.conflicts, ctx.conflict_cov = self._relevant_clusters(info, hits, evidence)
        return ctx

    def _select_evidence(self, info: QuestionInfo, hits: list[Hit]) -> list[Evidence]:
        cands: list[tuple[Hit, int, int, str, set[str]]] = []
        for h in hits:
            heading = set(content_stems(h.chunk.section))
            for a, b in split_sentences(h.chunk.text):
                s = h.chunk.text[a:b]
                if len(s) < 12 or s.lstrip().startswith("#"):
                    continue
                cands.append((h, a, b, s, heading))
        if not cands:
            return []
        dense_sims: list[float | None] = [None] * len(cands)
        if self.r.dense_active:
            try:
                qv = self.r.dense.embed_query(info.text)
                vecs = self.r.dense.embed_docs([c[3] for c in cands[:120]])
                for i, v in enumerate(vecs):
                    dense_sims[i] = float(v @ qv)
            except Exception:
                pass
        scored: list[Evidence] = []
        q_bi = _bigrams(_ordered_stems(info.text, QUESTION_FILLER))          # "payment terms" as a phrase, not two loose words
        for (h, a, b, s, heading), dsim in zip(cands, dense_sims):
            stems_s = set(content_stems(s))
            title = set(content_stems(re.sub(r"[_\-.]", " ", h.chunk.doc_name)))
            cov = self.coverage(info.terms, stems_s, heading, title)
            qs = extract_quantities(s)
            if dsim is not None:
                sc = 0.45 * cov + 0.35 * dense_norm(dsim) + 0.2 * h.rank_score
            else:
                sc = 0.7 * cov + 0.3 * h.rank_score
            if q_bi:
                hits_bi = len(q_bi & (_bigrams(_ordered_stems(s)) | _bigrams(_ordered_stems(h.chunk.section))))
                sc += min(0.2, 0.12 * hits_bi)
            if info.wants:
                sc += 0.12 if _has_wanted(qs, info.wants) else (-0.1 if info.strict else -0.04)
            if info.periods:
                sc += 0.1 if any(p in s.lower() for p in info.periods) else -0.05
            scored.append(Evidence(h.chunk, a, b, s, sc, cov, qs, h))
        scored.sort(key=lambda e: -e.score)
        anchors = self.anchors(info.terms)
        best = scored[0].score
        chosen: list[Evidence] = []
        per_doc: dict[str, int] = {}
        for e in scored:
            if len(chosen) >= 5:
                break
            if e.score < max(0.45 * best, 0.18):
                break
            if per_doc.get(e.chunk.doc_id, 0) >= 2:
                continue
            if chosen and not self.covers_anchor(anchors, set(content_stems(e.text)), set(content_stems(e.chunk.section))):
                continue
            norm = normalize_ws(e.text).lower()
            if any(norm == normalize_ws(c.text).lower() and c.chunk.doc_id == e.chunk.doc_id for c in chosen):
                continue
            chosen.append(e)
            per_doc[e.chunk.doc_id] = per_doc.get(e.chunk.doc_id, 0) + 1
        return chosen

    def _relevant_clusters(self, info: QuestionInfo, hits: list[Hit], evidence: list[Evidence]) -> tuple[list[dict], float]:
        if not self.clusters or not evidence:
            return [], 0.0
        hit_ids = {h.chunk.id for h in hits}
        top = evidence[:3]
        out: list[tuple[float, float, dict]] = []
        for cl in self.clusters:
            sources = [s for p in cl["positions"] for s in p["sources"]]
            mismatch = bool(info.wants) and cl["value_kind"] not in info.wants and cl["kind"] != "assertion"
            if mismatch and info.strict:
                continue
            if info.periods:
                text = " ".join(s["sentence"].lower() for s in sources)
                if not any(p in text for p in info.periods):
                    continue                        # question is about a specific month/year the conflict does not mention
            stems_: set[str] = {stem(t) for t in cl["topic"]}
            for s in sources:
                stems_ |= set(content_stems(s["sentence"])) | set(content_stems(s["section"]))
            if not self.covers_anchor(self.anchors(info.terms), stems_):
                continue
            cov = self.coverage(info.terms, stems_)
            direct = any(s["chunk_id"] == e.chunk.id and s["start"] < e.page_end and s["end"] > e.page_start for s in sources for e in top)
            in_hits = any(s["chunk_id"] in hit_ids for s in sources)
            thr = 0.5 if direct else (0.65 if in_hits else 0.85)
            if mismatch:                       # the question hints at another kind of value: only the very best evidence sentence may open it
                top1 = any(s["chunk_id"] == evidence[0].chunk.id and s["start"] < evidence[0].page_end and s["end"] > evidence[0].page_start for s in sources)
                thr = 0.8 if top1 else 9.0
            if cov >= thr:
                out.append(((2 if direct else 1) + cl["score"] + cov, cov, cl))
        out.sort(key=lambda t: -t[0])
        return [c for _, _, c in out[:2]], (out[0][1] if out else 0.0)


