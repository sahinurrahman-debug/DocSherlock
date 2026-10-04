"""Disputed points: corpus-wide (the Conflict board), per question, evidence for a question, and document comparison."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_session_id, owned_question
from app.core.database import get_db
from app.models.investigation import Question
from app.schemas.question import CompareIn
from app.services import board as board_service
from app.services import comparison, timeline
from app.services.corpus import corpus_cache
from app.services.llm import get_llm
from app.core.config import settings

router = APIRouter(prefix="/api", tags=["evidence"])


def _ids(document_ids: str | None) -> list[str] | None:
    return [x for x in (document_ids or "").split(",") if x] or None


@router.get("/conflicts")
def corpus_conflicts(document_ids: str | None = Query(default=None, description="comma-separated; default all READY documents"),
                     session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    """Every disputed point among the documents (same subject, incompatible values), clustered into positions."""
    corpus = corpus_cache.get(db, session_id, _ids(document_ids))
    return {"conflicts": corpus.clusters, "documents": len(corpus.docs), "claims": len(corpus.facts)}


@router.get("/casefile")
def casefile(document_ids: str | None = Query(default=None, description="comma-separated; default all READY documents"),
             session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    """What deserves attention in this document set - disputes, superseded or stale documents, unreadable scans, undated files - found without a question."""
    return corpus_cache.get(db, session_id, _ids(document_ids)).casefile


@router.get("/timeline")
def timeline_view(as_of: str | None = Query(default=None, description="YYYY-MM-DD: also report which value of each disputed point was in force on that date"),
                  document_ids: str | None = Query(default=None), session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    """Documents in date order, the history of every disputed point, and (with `as_of`) a snapshot of what was in force on that date."""
    try:
        day = timeline.parse_day(as_of) if as_of else None
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return timeline.build_timeline(corpus_cache.get(db, session_id, _ids(document_ids)), day)


@router.get("/board")
def case_board(document_ids: str | None = Query(default=None), session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    """The documents, the claims they disagree about, and which document amends which - as data for the Case Board."""
    return board_service.build_board(corpus_cache.get(db, session_id, _ids(document_ids)))


@router.get("/conflicts/{question_id}")
def question_conflicts(row: Question = Depends(owned_question)):
    """The conflicts recorded when this question was answered."""
    return {"question_id": row.id, "conflict_detected": row.conflict_detected, "conflicts": [c.data for c in row.conflicts]}


@router.get("/evidence/{question_id}")
def evidence(row: Question = Depends(owned_question)):
    """Citations (with exact offsets) and the evidence matrix behind an answer."""
    p = row.payload or {}
    return {"question_id": row.id, "level": row.level, "citations": p.get("citations", []), "evidence_matrix": p.get("evidence_matrix", []),
            "conflicts": p.get("conflicts", []), "caveats": p.get("caveats", [])}


@router.post("/compare")
def compare_documents(body: CompareIn, session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    """What changed between two documents (older -> newer by document date), with direction and size of each change."""
    if body.document_a == body.document_b:
        raise HTTPException(400, "Choose two different documents.")
    corpus = corpus_cache.get(db, session_id, [body.document_a, body.document_b])
    try:
        result = comparison.compare(corpus, body.document_a, body.document_b)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    result["engine"] = "rules"
    if body.use_llm and settings.llm_available:
        text = comparison.llm_summary(result, get_llm())
        if text:
            result["summary"], result["engine"] = text, settings.groq_model
    return result
