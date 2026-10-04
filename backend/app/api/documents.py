"""Document library: upload (background ingestion), list, inspect, edit date, delete, page viewer, demo set."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session_id, owned_document
from app.core.config import ROOT_DIR, settings
from app.core.database import get_db
from app.models.document import Claim, Document, Page
from app.schemas.document import ClaimOut, DocumentOut, DocumentPatch, PageOut, PageResponse, UploadResponse, UploadResult
from app.services import ingestion
from app.services.render import render_page
from app.services.vectorstore import get_vector_store

router = APIRouter(prefix="/api/documents", tags=["documents"])
SAMPLE_DIR = ROOT_DIR / "sample-documents" / "corpus"


def _list(db: Session, session_id: str) -> list[Document]:
    return list(db.scalars(select(Document).where(Document.session_id == session_id).order_by(Document.uploaded_at)))


def _upload_one(db: Session, session_id: str, filename: str, data: bytes) -> UploadResult:
    try:
        doc, dup, msg = ingestion.create_document(db, session_id, filename, data)
    except ingestion.IngestError as exc:
        return UploadResult(filename=filename, ok=False, error=str(exc))
    if not dup:
        ingestion.submit(doc.id)                         # background worker (sync in tests)
        db.refresh(doc)
    return UploadResult(filename=filename, ok=True, duplicate=dup, message=msg, document=DocumentOut.model_validate(doc))


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload(files: list[UploadFile] = File(...), session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    """Accepts several files; returns 202 immediately - poll GET /api/documents for status stages."""
    results = []
    for f in files:
        data = await f.read(int(settings.max_upload_mb * 1024 * 1024) + 1)
        results.append(_upload_one(db, session_id, f.filename or "document", data))
    return UploadResponse(results=results, documents=[DocumentOut.model_validate(d) for d in _list(db, session_id)])


@router.post("/demo", response_model=UploadResponse, status_code=202)
def load_demo(session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    """Load the bundled sample documents (several deliberately contradict each other) into this workspace."""
    if not SAMPLE_DIR.exists():
        raise HTTPException(404, "Sample documents not found. Run `python sample-documents/generate.py`.")
    results = [_upload_one(db, session_id, p.name, p.read_bytes()) for p in sorted(SAMPLE_DIR.iterdir())
               if p.is_file() and p.suffix.lower() in settings.allowed_extensions]
    return UploadResponse(results=results, documents=[DocumentOut.model_validate(d) for d in _list(db, session_id)])


@router.get("", response_model=list[DocumentOut])
def list_documents(session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    return _list(db, session_id)


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc: Document = Depends(owned_document)):
    return doc


@router.patch("/{doc_id}", response_model=DocumentOut)
def patch_document(body: DocumentPatch, doc: Document = Depends(owned_document), db: Session = Depends(get_db)):
    try:
        return ingestion.set_doc_date(db, doc, body.doc_date)
    except ingestion.IngestError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc: Document = Depends(owned_document), db: Session = Depends(get_db)):
    ingestion.delete_document(db, doc)
    return Response(status_code=204)


@router.delete("", status_code=204)
def reset_workspace(session_id: str = Depends(get_session_id), db: Session = Depends(get_db)):
    for d in _list(db, session_id):
        ingestion.delete_document(db, d)
    try:
        get_vector_store().delete_session(session_id)
    except Exception:
        pass
    return Response(status_code=204)


# ---- viewer ------------------------------------------------------------------------------------
def _page(db: Session, doc: Document, n: int) -> Page:
    page = db.scalar(select(Page).where(Page.document_id == doc.id, Page.page_number == n))
    if page is None:
        raise HTTPException(404, "Page not found")
    return page


@router.get("/{doc_id}/pages/{n}", response_model=PageResponse)
def get_page(n: int, doc: Document = Depends(owned_document), db: Session = Depends(get_db)):
    page = _page(db, doc, n)
    return PageResponse(document=DocumentOut.model_validate(doc), n_pages=doc.n_pages,
                        page=PageOut(number=page.page_number, text=page.text, ocr_conf=page.ocr_conf, method=page.method,
                                     has_image=doc.file_type == ".pdf" or doc.file_type in settings.image_extensions))


@router.get("/{doc_id}/pages/{n}/image")
def page_image(n: int, start: int = -1, end: int = -1, scale: float = 1.6, doc: Document = Depends(owned_document), db: Session = Depends(get_db)):
    """The page as PNG with the cited passage highlighted (`start`/`end` are offsets into the page text)."""
    page = _page(db, doc, n)
    path = ingestion.ensure_file(db, doc)
    if path is None:
        raise HTTPException(404, "The original file is no longer stored")
    quote = page.text[start:end] if 0 <= start < end <= len(page.text) else ""
    png = render_page(path, doc.file_type, page, quote, max(0.8, min(scale, 3.0)))
    if png is None:
        raise HTTPException(415, "This document type has no page image")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/{doc_id}/file")
def original_file(doc: Document = Depends(owned_document), db: Session = Depends(get_db)):
    path = ingestion.ensure_file(db, doc)
    if path is None:
        raise HTTPException(404, "The original file is no longer stored")
    return FileResponse(Path(path), filename=doc.filename)


@router.get("/{doc_id}/claims", response_model=list[ClaimOut])
def claims(doc: Document = Depends(owned_document), db: Session = Depends(get_db)):
    rows = db.scalars(select(Claim).where(Claim.document_id == doc.id).order_by(Claim.page_number, Claim.id)).all()
    return [ClaimOut(id=c.id, page=c.page_number, section=c.section, sentence=c.sentence, subject=c.subject, kind=c.kind, value=c.value_text) for c in rows]
