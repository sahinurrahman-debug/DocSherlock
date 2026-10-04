"""Investigations: named cases holding a history of questions, with a Markdown report export."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session_id, owned_investigation
from app.api.questions import question_payload
from app.core.database import get_db
from app.models.document import Document
from app.models.investigation import Investigation, Question
from app.schemas.question import InvestigationDetail, InvestigationIn, InvestigationOut
from app.services.corpus import corpus_cache
from app.services.report import render_markdown

router = APIRouter(prefix="/api/investigations", tags=["investigations"])


def _out(inv: Investigation, n: int) -> InvestigationOut:
    return InvestigationOut(id=inv.id, name=inv.name, status=inv.status, created_at=inv.created_at, updated_at=inv.updated_at, n_questions=n)


@router.post("", response_model=InvestigationOut, status_code=201)
def create(body: InvestigationIn, session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    inv = Investigation(id=uuid.uuid4().hex[:12], session_id=session_id, name=(body.name or "New investigation").strip() or "New investigation")
    db.add(inv)
    db.commit()
    return _out(inv, 0)


@router.get("", response_model=list[InvestigationOut])
def list_all(session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Question.investigation_id, func.count()).where(Question.session_id == session_id).group_by(Question.investigation_id)).all())
    rows = db.scalars(select(Investigation).where(Investigation.session_id == session_id).order_by(Investigation.updated_at.desc())).all()
    return [_out(i, counts.get(i.id, 0)) for i in rows]


@router.get("/{inv_id}", response_model=InvestigationDetail)
def detail(inv: Investigation = Depends(owned_investigation)):
    return InvestigationDetail(id=inv.id, name=inv.name, status=inv.status, created_at=inv.created_at, updated_at=inv.updated_at,
                               n_questions=len(inv.questions), questions=[question_payload(q) for q in inv.questions])


@router.patch("/{inv_id}", response_model=InvestigationOut)
def rename(body: InvestigationIn, inv: Investigation = Depends(owned_investigation), db: Session = Depends(get_db)):
    if body.name and body.name.strip():
        inv.name = body.name.strip()
        db.commit()
    return _out(inv, len(inv.questions))


@router.delete("/{inv_id}", status_code=204)
def delete(inv: Investigation = Depends(owned_investigation), db: Session = Depends(get_db)):
    db.delete(inv)
    db.commit()
    return Response(status_code=204)


@router.get("/{inv_id}/report", response_class=PlainTextResponse)
def report(pinned_only: bool = False, inv: Investigation = Depends(owned_investigation), db: Session = Depends(get_db)):
    """Markdown report: every finding (or only pinned ones) with sources, caveats and the corpus-wide conflict register."""
    qs = [q for q in inv.questions if q.pinned or not pinned_only]
    docs = list(db.scalars(select(Document).where(Document.session_id == inv.session_id, Document.status == "READY").order_by(Document.uploaded_at)))
    corpus = corpus_cache.get(db, inv.session_id, None)
    notes = [{"result": question_payload(q), "comment": q.note} for q in qs]
    doc_dicts = [{"name": d.filename, "n_pages": d.n_pages, "doc_date": d.doc_date, "ocr_used": d.ocr_used, "ocr_conf": d.ocr_conf} for d in docs]
    md = render_markdown(notes, doc_dicts, corpus.clusters, title=f"DocSherlock investigation: {inv.name}")
    return PlainTextResponse(md, media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="docsherlock-report.md"'})
