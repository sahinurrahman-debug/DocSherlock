"""Question answering orchestration: scope -> retrieve -> evidence -> conflict check -> LLM (Groq) or rules fallback -> verify ->
uncertainty level -> persist."""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.investigation import Citation as CitationRow, ConflictRecord, Investigation, Question
from app.services import comparison, timeline
from app.services.citations import CitationBook
from app.services.corpus import Corpus, corpus_cache
from app.services.embeddings import get_embeddings
from app.services.evidence import Analyzer, contextualize
from app.services.extractive import compose_extractive
from app.services.facts import extract_quantities
from app.services.generator import compose_llm
from app.services.llm import LLMClient, LLMError, LLMRateLimited, get_llm
from app.services.uncertainty import level_for
from app.utils.text import clip

log = logging.getLogger("docsherlock.qa")
StageCb = Callable[[str, str], None]


def _noop(stage: str, detail: str = "") -> None:
    return None


def matrix_from_citations(citations: list[dict]) -> list[dict]:
    """Evidence matrix rows for answers produced without structured claim extraction (rule engine)."""
    rows = []
    for c in citations:
        if c["role"] == "lead":
            continue
        qs = extract_quantities(c["quote"])
        q = next((x for x in qs if x.kind != "number"), qs[0] if qs else None)
        subject = clip(re.sub(re.escape(q.raw), "", c["quote"]) if q else c["quote"], 70) if q else clip(c["quote"], 70)
        rows.append({"subject": subject, "predicate": "", "value": q.raw if q else "", "date": c.get("doc_date") or "", "document": c["doc_name"],
                     "doc_id": c["doc_id"], "page": c["page"], "section": c["section"], "cite": c["id"], "quote": c["quote"], "verified": True})
    return rows


def _engine_info(name: str, model: str = "", meta=None, fallback: bool = False, reason: str | None = None) -> dict:
    return {"name": name, "model": model, "fallback": fallback, "reason": reason,
            "tokens": ({"prompt": meta.prompt_tokens, "completion": meta.completion_tokens, "latency_ms": meta.latency_ms} if meta else None),
            "strict_schema": bool(meta.strict) if meta else False}


def ask(db: Session, *, session_id: str, investigation: Investigation, question: str, doc_ids: list[str] | None = None, mode: str = "auto",
        on_stage: StageCb = _noop, llm: LLMClient | None = None, as_of: str | None = None, semantic: bool = True) -> dict:
    """`as_of` ('YYYY-MM-DD') answers using only documents that existed by then; `semantic=False` skips vector search (used by the Trust Lab)."""
    t0 = time.perf_counter()
    question = re.sub(r"\s+", " ", question or "").strip()
    if not question:
        raise ValueError("Please enter a question.")
    if len(question) > 1500:
        raise ValueError("Question is too long (max 1500 characters).")
    llm = llm or get_llm()

    as_of_info: dict | None = None
    if as_of:
        day = timeline.parse_day(as_of)                            # ValueError -> HTTP 400
        everything = corpus_cache.get(db, session_id, doc_ids)
        keep, excluded = timeline.documents_as_of(everything, day)
        as_of_info = {"date": day, "documents_used": len(keep), "documents_total": len(everything.docs), "excluded": excluded}
        if not keep:
            res = _empty(question, f"No document is dated on or before {day}, so there is nothing to answer from at that point in time.")
            res["as_of"] = as_of_info
            return _persist(db, investigation, session_id, res, t0, t0)
        doc_ids = keep

    def done(resp: dict, t_end: float) -> dict:
        if as_of_info:
            later = [e for e in as_of_info["excluded"] if e["reason"] == "later"]
            undated = [e for e in as_of_info["excluded"] if e["reason"] == "undated"]
            note = f"Answered as of {as_of_info['date']}, using {as_of_info['documents_used']} of {as_of_info['documents_total']} documents."
            if later:
                note += f" Written later and ignored: {', '.join(e['name'] for e in later[:4])}{' and more' if len(later) > 4 else ''}."
            if undated:
                note += f" Undated, so left out: {', '.join(e['name'] for e in undated[:3])}{' and more' if len(undated) > 3 else ''}."
            resp["as_of"] = as_of_info
            resp["caveats"] = [note] + list(resp.get("caveats", []))
        return _persist(db, investigation, session_id, resp, t0, t_end)

    corpus = corpus_cache.get(db, session_id, doc_ids)
    if not corpus.docs:
        return _persist(db, investigation, session_id, _empty(question, "No documents are ready yet. Upload documents (or load the sample set) and wait until they show READY."), t0, t0)

    prior = [{"question": q.question, "answer": q.answer} for q in investigation.questions[-3:]]
    emb = get_embeddings()
    store = None
    if settings.dense_enabled and semantic:
        from app.services.vectorstore import get_vector_store      # lazy: the Qdrant client costs ~120 MB, unused in keyword-only mode
        store = get_vector_store()
    retriever = corpus.retriever(emb, store)

    # ---- comparison questions ("what changed between the 2022 and 2024 policies?") -------------------
    pair = comparison.resolve_documents(question, corpus)
    if pair:
        on_stage("comparing", "Comparing the two documents")
        return done(_compare_answer(corpus, question, pair, llm, mode), time.perf_counter())

    on_stage("retrieving", "Searching the documents")
    eff = contextualize(question, prior, retriever)
    analyzer = Analyzer(retriever, corpus.chunk_by_id, corpus.clusters, len(corpus.docs))
    on_stage("checking_conflicts", "Checking evidence and conflicts")
    ctx = analyzer.build(question, eff, k=settings.final_k)
    t1 = time.perf_counter()

    book = CitationBook()
    engine = _engine_info("rules")
    result: dict | None = None
    reason: str | None = None
    want_llm = mode != "rules" and bool(ctx.hits)
    if want_llm and not llm.available:
        reason = "No LLM key is configured (set GROQ_API_KEY) - answered by the rule-based engine." if mode == "llm" else None
    elif want_llm:
        on_stage("reasoning", f"Asking {settings.groq_model}")
        try:
            result, meta = compose_llm(ctx, book, corpus.chunk_by_id, prior, llm)
            engine = _engine_info(settings.llm_provider, meta.model, meta)
            if meta.notes:
                result["caveats"] = list(meta.notes) + result.get("caveats", [])
        except LLMRateLimited as exc:
            reason = f"The LLM rate limit was reached ({exc}) - answered by the rule-based engine instead."
        except LLMError as exc:
            reason = f"The LLM was unavailable ({clip(str(exc), 110)}) - answered by the rule-based engine instead."
        except Exception as exc:                        # never let an unexpected LLM-path bug break the answer
            log.exception("LLM path failed")
            reason = f"The LLM path failed ({exc.__class__.__name__}) - answered by the rule-based engine instead."
        if result is None:
            book = CitationBook()
            engine = _engine_info("rules", fallback=True, reason=reason)
    if result is None:
        on_stage("composing", "Composing the answer")
        result = compose_extractive(ctx, book, corpus.chunk_by_id)
        if reason:
            result["caveats"] = [reason] + result.get("caveats", [])
    on_stage("verifying", "Verifying citations")
    t2 = time.perf_counter()

    citations = [c.to_dict() for c in book.items]
    conf = result["confidence"]
    resp = {
        "question": question, "effective_question": eff, "status": result["status"], "headline": result.get("headline", ""), "answer": result["answer"],
        "confidence": conf, "level": level_for(result["status"], conf["score"]), "citations": citations, "conflicts": result.get("conflicts", []),
        "caveats": result.get("caveats", []), "missing_terms": ctx.missing_terms, "engine": engine,
        "evidence_matrix": result.get("matrix") or matrix_from_citations(citations),
        "trace": {"query_terms": ctx.info.terms, "question_type": ctx.info.qtype, "wants": sorted(ctx.info.wants), "dense": ctx.dense_active,
                  "channels": getattr(retriever, "channels_used", []), "scope_documents": len(corpus.docs), "scope_chunks": len(corpus.chunks),
                  "relevant_conflicts": len(ctx.conflicts),
                  "hits": [{"doc": h.chunk.doc_name, "page": h.chunk.page if h.chunk.paged else None, "section": h.chunk.section,
                            "rank": round(h.rank_score, 3), "relevance": round(h.relevance, 3), "coverage": round(h.coverage, 3),
                            "rerank": round(h.rerank, 2) if h.rerank is not None else None, "preview": clip(h.chunk.text, 140)} for h in ctx.hits]},
        "timings_ms": {"retrieve": round((t1 - t0) * 1000), "compose": round((t2 - t1) * 1000)},
    }
    return done(resp, time.perf_counter())


# ------------------------------------------------------------------------------------------------
def _empty(question: str, msg: str) -> dict:
    return {"question": question, "effective_question": question, "status": "insufficient", "headline": "", "answer": msg,
            "confidence": {"score": 0.0, "label": "None", "reasons": []}, "level": "INSUFFICIENT", "citations": [], "conflicts": [],
            "caveats": [], "missing_terms": [], "engine": _engine_info("rules"), "evidence_matrix": [], "trace": {"hits": []}, "timings_ms": {}}


def _compare_answer(corpus: Corpus, question: str, pair: tuple[str, str], llm: LLMClient, mode: str) -> dict:
    cmp = comparison.compare(corpus, *pair)
    engine = _engine_info("rules")
    if mode != "rules" and llm.available:
        text = comparison.llm_summary(cmp, llm)
        if text:
            cmp["summary"] = text
            engine = _engine_info(settings.llm_provider, settings.groq_model)
    book = CitationBook()

    def cite(src: dict, score: float = 0.9) -> str | None:
        ch = corpus.chunk_by_id.get(src["chunk_id"])
        return book.add(ch, src["start"], src["end"], src["sentence"], score, role="support").id if ch else None

    lines = [f"**{cmp['summary']}**" if cmp["changes"] else cmp["summary"], ""]
    for ch in cmp["changes"][:12]:
        co, cn = cite(ch["old"]["source"]), cite(ch["new"]["source"])
        ch["old"]["cite"], ch["new"]["cite"] = co, cn
        lines.append(f"- {ch['topic']}: **{ch['old']['value']}** [{co}] → **{ch['new']['value']}** [{cn}] - {ch['description']}")
    status = "answered" if cmp["changes"] else "partial"
    score = 0.5 if not cmp["changes"] else (0.8 if cmp["ordered_by_date"] else 0.62)
    reasons = [{"text": f"{len(cmp['changes'])} differing value(s) found by matching claims about the same subject", "effect": "+" if cmp["changes"] else "-"},
               {"text": "Documents are dated, so the direction of change is reliable" if cmp["ordered_by_date"] else "A document is undated - direction of change follows your selection", "effect": "+" if cmp["ordered_by_date"] else "-"}]
    citations = [c.to_dict() for c in book.items]
    return {"question": question, "effective_question": question, "status": status, "headline": f"{len(cmp['changes'])} change(s)" if cmp["changes"] else "No differences found",
            "answer": "\n".join(lines).strip(), "confidence": {"score": score, "label": "High" if score >= 0.68 else "Medium", "reasons": reasons},
            "level": level_for(status, score), "citations": citations, "conflicts": [], "caveats": cmp["caveats"], "missing_terms": [], "engine": engine,
            "evidence_matrix": matrix_from_citations(citations), "comparison": cmp, "trace": {"intent": "compare", "hits": []}, "timings_ms": {}}


def _persist(db: Session, inv: Investigation, session_id: str, resp: dict, t0: float, t1: float) -> dict:
    resp["timings_ms"] = {**resp.get("timings_ms", {}), "total": round((t1 - t0) * 1000)}
    qid = uuid.uuid4().hex[:12]
    resp.update({"id": qid, "investigation_id": inv.id, "conflict_detected": bool(resp["conflicts"]), "pinned": False, "note": ""})
    row = Question(id=qid, investigation_id=inv.id, session_id=session_id, question=resp["question"], effective_question=resp.get("effective_question", ""),
                   answer=resp["answer"], headline=resp.get("headline", ""), status=resp["status"], level=resp["level"],
                   confidence_score=float(resp["confidence"]["score"]), conflict_detected=resp["conflict_detected"],
                   engine=(resp["engine"]["model"] or resp["engine"]["name"]), payload=resp)
    for c in resp["citations"]:
        row.citations.append(CitationRow(cite_id=c["id"], document_id=c["doc_id"], document_name=c["doc_name"], page=c["page"], section=c["section"],
                                         chunk_id=c["chunk_id"], relevance_score=c["score"], quote=c["quote"], start_char=c["start"], end_char=c["end"],
                                         role=c["role"], side=c.get("side")))
    for cl in resp["conflicts"]:
        pos = cl["positions"]
        row.conflicts.append(ConflictRecord(cluster_id=str(cl.get("id", "")), claim_a=pos[0]["value"] if pos else "", claim_b=pos[1]["value"] if len(pos) > 1 else "",
                                            source_a=", ".join(s["doc_name"] for s in pos[0]["sources"])[:400] if pos else "",
                                            source_b=", ".join(s["doc_name"] for s in pos[1]["sources"])[:400] if len(pos) > 1 else "",
                                            severity=cl.get("severity", "medium"), data=cl))
    inv.questions.append(row)
    db.add(row)
    db.commit()
    resp["created_at"] = row.created_at.isoformat()
    return resp
