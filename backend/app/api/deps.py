"""Request dependencies: anonymous browser sessions (tenant isolation without accounts) and owned-resource lookups."""
from __future__ import annotations

import re

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document import Document
from app.models.investigation import Investigation, Question

_SESSION_RE = re.compile(r"^[A-Za-z0-9_\-]{4,64}$")


def get_session_id(x_session_id: str | None = Header(default=None)) -> str:
    """The browser generates a random id and sends it on every request; every record is scoped to it."""
    if x_session_id is None:
        return "public"
    if not _SESSION_RE.match(x_session_id):
        raise HTTPException(400, "Invalid X-Session-Id header")
    return x_session_id


def owned_document(doc_id: str, session_id: str = Depends(get_session_id), db: Session = Depends(get_db)) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.session_id != session_id:
        raise HTTPException(404, "Document not found")
    return doc


def owned_investigation(inv_id: str, session_id: str = Depends(get_session_id), db: Session = Depends(get_db)) -> Investigation:
    inv = db.get(Investigation, inv_id)
    if inv is None or inv.session_id != session_id:
        raise HTTPException(404, "Investigation not found")
    return inv


def owned_question(question_id: str, session_id: str = Depends(get_session_id), db: Session = Depends(get_db)) -> Question:
    q = db.get(Question, question_id)
    if q is None or q.session_id != session_id:
        raise HTTPException(404, "Question not found")
    return q
