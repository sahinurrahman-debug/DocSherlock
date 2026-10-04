"""Ask questions (plain JSON or Server-Sent Events with live stage updates), fetch past answers, pin / annotate them."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_session_id, owned_question
from app.core.database import SessionLocal, get_db
from app.models.investigation import Investigation, Question
from app.schemas.question import ChallengeIn, QuestionIn, QuestionOut, QuestionPatch
from app.services import evidencepack, qa, redteam
from app.services.llm import get_llm
from app.utils.text import clip

router = APIRouter(prefix="/api/questions", tags=["questions"])


def question_payload(row: Question) -> dict:
    """Stored answer + the mutable fields (pin / note)."""
    d = dict(row.payload or {})
    d.update({"id": row.id, "investigation_id": row.investigation_id, "pinned": row.pinned, "note": row.note,
              "created_at": row.created_at.isoformat() if row.created_at else None})
    return d


def ensure_investigation(db: Session, session_id: str, inv_id: str | None, first_question: str) -> Investigation:
    if inv_id:
        inv = db.get(Investigation, inv_id)
        if inv is None or inv.session_id != session_id:
            raise HTTPException(404, "Investigation not found")
        return inv
    inv = Investigation(id=uuid.uuid4().hex[:12], session_id=session_id, name=clip(first_question, 70))
    db.add(inv)
    db.commit()
    return inv


@router.post("", response_model=QuestionOut)
def ask(body: QuestionIn, session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    inv = ensure_investigation(db, session_id, body.investigation_id, body.question)
    try:
        return qa.ask(db, session_id=session_id, investigation=inv, question=body.question, doc_ids=body.document_ids, mode=body.mode, as_of=body.as_of)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/stream")
async def ask_stream(body: QuestionIn, session_id: str = Depends(get_session_id)):
    """Same as POST /api/questions but streams `stage` events while the pipeline runs, then one `result` event."""
    q: queue.Queue = queue.Queue()

    def work() -> None:
        db = SessionLocal()
        try:
            inv = ensure_investigation(db, session_id, body.investigation_id, body.question)
            q.put(("investigation", {"id": inv.id, "name": inv.name}))
            res = qa.ask(db, session_id=session_id, investigation=inv, question=body.question, doc_ids=body.document_ids, mode=body.mode, as_of=body.as_of,
                         on_stage=lambda stage, detail="": q.put(("stage", {"stage": stage, "detail": detail})))
            q.put(("result", res))
        except HTTPException as exc:
            q.put(("error", {"detail": exc.detail, "status": exc.status_code}))
        except ValueError as exc:
            q.put(("error", {"detail": str(exc), "status": 400}))
        except Exception as exc:                                  # pragma: no cover
            q.put(("error", {"detail": f"{exc.__class__.__name__}: {exc}", "status": 500}))
        finally:
            db.close()
            q.put(None)

    threading.Thread(target=work, daemon=True, name="ask-stream").start()

    async def events():
        while True:
            item = await asyncio.to_thread(q.get)
            if item is None:
                break
            name, data = item
            yield f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{question_id}", response_model=QuestionOut)
def get_question(row: Question = Depends(owned_question)):
    return question_payload(row)


@router.post("/{question_id}/challenge")
def challenge_answer(body: ChallengeIn | None = None, row: Question = Depends(owned_question), db: Session = Depends(get_db)):
    """Red-team an answer: try to break it (quotes, figures, ignored contradictions, exceptions, optionally an LLM adversary) and store the verdict with it."""
    body = body or ChallengeIn()
    result = redteam.challenge(db, row.session_id, dict(row.payload or {}), get_llm(), use_llm=body.use_llm)
    row.payload = {**(row.payload or {}), "redteam": result}
    db.commit()
    return result


@router.get("/{question_id}/pack")
def evidence_pack(row: Question = Depends(owned_question), db: Session = Depends(get_db)):
    """The answer as a PDF: verbatim quotes, the original pages with the passages marked, confidence reasoning, document fingerprints."""
    pdf = evidencepack.build_pack(db, row)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="DocSherlock_evidence_{row.id}.pdf"', "Cache-Control": "no-store"})


@router.patch("/{question_id}", response_model=QuestionOut)
def patch_question(body: QuestionPatch, row: Question = Depends(owned_question), db: Session = Depends(get_db)):
    if body.pinned is not None:
        row.pinned = body.pinned
    if body.note is not None:
        row.note = body.note
    db.commit()
    return question_payload(row)


@router.delete("/{question_id}", status_code=204)
def delete_question(row: Question = Depends(owned_question), db: Session = Depends(get_db)):
    db.delete(row)
    db.commit()
