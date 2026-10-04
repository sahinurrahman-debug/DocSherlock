"""Document ingestion: validate -> store -> (background) extract -> OCR -> chunk -> claims -> embed -> index.

Upload returns immediately (202); a worker pool advances each document through visible status stages:
UPLOADED -> PROCESSING -> EXTRACTING -> (OCR) -> CHUNKING -> EMBEDDING -> INDEXING -> READY | FAILED
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain import Chunk
from app.models.document import Claim, DocChunk, Document, EmbeddingCache, Page
from app.services import extractor
from app.services.chunker import chunk_document
from app.services.claims import claim_row, extract_claims
from app.services.corpus import corpus_cache
from app.services.embeddings import EmbeddingService, get_embeddings

log = logging.getLogger("docsherlock.ingest")

STAGES = ["UPLOADED", "PROCESSING", "EXTRACTING", "OCR", "CHUNKING", "EMBEDDING", "INDEXING", "READY", "FAILED"]
PROGRESS = {"UPLOADED": 5, "PROCESSING": 8, "EXTRACTING": 20, "OCR": 35, "CHUNKING": 55, "EMBEDDING": 72, "INDEXING": 90, "READY": 100, "FAILED": 100}


def get_vector_store():
    from app.services.vectorstore import get_vector_store as _get      # lazy import (see qa.py)
    return _get()


class IngestError(Exception):
    pass


_executor: ThreadPoolExecutor | None = None
_exec_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _exec_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=max(1, settings.ingest_workers), thread_name_prefix="ingest")
        return _executor


# ------------------------------------------------------------------------------------------------
# upload
# ------------------------------------------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    base = Path(name or "document").name
    base = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", base).strip(" .") or "document"
    return base[:150]


def _unique_name(db: Session, session_id: str, name: str) -> str:
    existing = set(db.scalars(select(Document.filename).where(Document.session_id == session_id)))
    if name not in existing:
        return name
    p = Path(name)
    i = 2
    while f"{p.stem} ({i}){p.suffix}" in existing:
        i += 1
    return f"{p.stem} ({i}){p.suffix}"


def file_path(doc: Document) -> Path:
    return settings.upload_dir / doc.session_id / f"{doc.id}{doc.file_type}"


def ensure_file(db: Session, doc: Document) -> Path | None:
    """Return the original file, restoring it from the database copy if the disk was wiped (ephemeral hosts)."""
    p = file_path(doc)
    if p.exists():
        return p
    blob = db.execute(select(Document.file_blob).where(Document.id == doc.id)).scalar()
    if blob:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
        return p
    return None


def create_document(db: Session, session_id: str, filename: str, data: bytes) -> tuple[Document, bool, str]:
    """Validate and store an upload. Returns (document, is_duplicate, message)."""
    filename = sanitize_filename(filename)
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise IngestError(f"Unsupported file type '{ext or 'unknown'}'. Supported: {', '.join(sorted(settings.allowed_extensions))}")
    if not data:
        raise IngestError("The file is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise IngestError(f"File is larger than the {settings.max_upload_mb:g} MB limit.")
    if ext == ".pdf" and not data.lstrip()[:5] == b"%PDF-":
        raise IngestError("This does not look like a PDF file (missing %PDF header).")
    if ext == ".docx" and data[:2] != b"PK":
        raise IngestError("This does not look like a DOCX file (not a zip container).")
    sha = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Document).where(Document.session_id == session_id, Document.sha256 == sha))
    if dup is not None:
        if dup.status != "FAILED":
            return dup, True, f"Identical to '{dup.filename}', which is already in this workspace."
        delete_document(db, dup)            # retry a failed upload from scratch
    doc = Document(id=uuid.uuid4().hex[:12], session_id=session_id, filename=_unique_name(db, session_id, filename), file_type=ext,
                   file_size=len(data), sha256=sha, status="UPLOADED", progress=PROGRESS["UPLOADED"])
    if settings.store_file_blobs and len(data) <= settings.max_blob_mb * 1024 * 1024:
        doc.file_blob = data
    p = file_path(doc)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    db.add(doc)
    db.commit()
    return doc, False, ""


def submit(doc_id: str) -> None:
    if settings.ingest_mode == "sync":
        process_document(doc_id)
    else:
        _pool().submit(_safe_process, doc_id)


def _safe_process(doc_id: str) -> None:
    try:
        process_document(doc_id)
    except Exception:                                  # pragma: no cover - process_document already records failures
        log.exception("ingestion crashed for %s", doc_id)


# ------------------------------------------------------------------------------------------------
# processing
# ------------------------------------------------------------------------------------------------
def _set_stage(db: Session, doc: Document, stage: str, error: str | None = None) -> None:
    doc.status, doc.progress = stage, PROGRESS.get(stage, doc.progress)
    if error is not None:
        doc.error = error
    db.commit()


def embed_texts(db: Session, texts: list[str], emb: EmbeddingService) -> np.ndarray:
    """Dense embeddings with a persistent cache keyed by (model, text)."""
    keys = [emb.cache_key(t) for t in texts]
    found = {r.key: np.frombuffer(r.vec, dtype=np.float32) for r in db.scalars(select(EmbeddingCache).where(EmbeddingCache.key.in_(keys)))} if keys else {}
    missing = [i for i, k in enumerate(keys) if k not in found]
    if missing:
        vecs = emb.embed_docs([texts[i] for i in missing])
        for i, v in zip(missing, vecs):
            found[keys[i]] = v
            db.merge(EmbeddingCache(key=keys[i], vec=v.astype(np.float32).tobytes()))
        db.commit()
    return np.stack([found[k] for k in keys]) if keys else np.zeros((0, 384), dtype=np.float32)


def _wait_for_models(emb: EmbeddingService, timeout_s: float = 180.0) -> bool:
    """Block this worker (never a request thread) until the dense model is ready, loading it if nobody started it."""
    if not settings.dense_enabled:
        return False
    emb.warmup()
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if emb.dense_m.ready:
            return True
        if emb.dense_m.error:
            return False
        time.sleep(0.3)
    return False


def index_document(db: Session, doc: Document, chunks: list[Chunk], emb: EmbeddingService) -> bool:
    """Embed + upsert the chunks of one document into Qdrant. Returns True when vectors were written."""
    if not chunks or not _wait_for_models(emb):
        return False
    store = get_vector_store()
    dense = embed_texts(db, [c.index_text for c in chunks], emb)
    sparse = emb.sparse_docs([c.index_text for c in chunks]) if emb.sparse_m.ready or _wait_sparse(emb) else None
    store.delete_document(doc.id)
    store.upsert(doc.session_id, chunks, dense.tolist(), sparse)
    return True


def _wait_sparse(emb: EmbeddingService, timeout_s: float = 60.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if emb.sparse_m.ready:
            return True
        if emb.sparse_m.error:
            return False
        time.sleep(0.2)
    return False


def process_document(doc_id: str) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        try:
            _process(db, doc)
        except extractor.ExtractionError as exc:
            db.rollback()
            doc = db.get(Document, doc_id)
            _set_stage(db, doc, "FAILED", str(exc))
        except Exception as exc:
            log.exception("processing failed for %s", doc_id)
            db.rollback()
            doc = db.get(Document, doc_id)
            _set_stage(db, doc, "FAILED", f"Unexpected error: {exc.__class__.__name__}: {exc}")
        finally:
            corpus_cache.bump(doc.session_id if doc else "")
    finally:
        db.close()


def _process(db: Session, doc: Document) -> None:
    _set_stage(db, doc, "PROCESSING")
    data = ensure_file(db, doc)
    if data is None:
        raise extractor.ExtractionError("The stored file is missing.")
    raw = data.read_bytes()
    _set_stage(db, doc, "EXTRACTING")
    ex = extractor.extract(doc.filename, raw, on_stage=lambda s: _set_stage(db, doc, s))

    _set_stage(db, doc, "CHUNKING")
    doc_date, date_src = extractor.detect_doc_date(doc.filename, ex)
    full_text = "\n".join(p.text for p in ex.pages)
    confs = [p.ocr_conf for p in ex.pages if p.ocr_conf is not None]
    title = ex.meta.get("title")
    db.execute(delete(Page).where(Page.document_id == doc.id))
    db.execute(delete(DocChunk).where(DocChunk.document_id == doc.id))
    db.execute(delete(Claim).where(Claim.document_id == doc.id))
    page_rows: dict[int, Page] = {}
    for p in ex.pages:
        first_heading = next((ln.lstrip("#").strip() for ln in p.text.split("\n") if ln.startswith("#")), None)
        row = Page(document_id=doc.id, page_number=p.number, text=p.text, section=(first_heading or None), ocr_used=p.ocr_conf is not None,
                   ocr_conf=p.ocr_conf, method=p.method, boxes=p.boxes, width=p.width, height=p.height)
        db.add(row)
        page_rows[p.number] = row
    db.flush()
    chunks = chunk_document(doc.id, doc.filename, ex.pages, ex.paged, doc_date, title)
    for c in chunks:
        db.add(DocChunk(id=c.id, document_id=doc.id, session_id=doc.session_id, page_id=page_rows[c.page].id, page_number=c.page,
                        chunk_index=c.idx, text=c.text, section=c.section, start_char=c.start, end_char=c.end, ocr_conf=c.ocr_conf))
    facts = extract_claims(chunks, title)
    for f in facts:
        db.add(claim_row(f, doc.session_id))
    doc.n_pages, doc.paged, doc.n_chunks, doc.n_claims, doc.n_chars = len(ex.pages), ex.paged, len(chunks), len(facts), len(full_text)
    doc.ocr_used, doc.ocr_conf = bool(confs), (sum(confs) / len(confs)) if confs else None
    doc.doc_date, doc.doc_date_source, doc.title, doc.warnings = doc_date, date_src, title, list(ex.warnings)
    db.commit()

    emb = get_embeddings()
    _set_stage(db, doc, "EMBEDDING")
    try:
        _set_stage(db, doc, "INDEXING")
        doc.indexed = index_document(db, doc, chunks, emb)
    except Exception as exc:                            # vector index trouble must not lose the document: lexical retrieval still works
        log.warning("vector indexing failed for %s: %s", doc.id, exc)
        doc.indexed = False
        doc.warnings = list(doc.warnings) + [f"Semantic indexing unavailable ({exc.__class__.__name__}); keyword retrieval is used for this document."]
    doc.status, doc.progress = ("READY" if full_text.strip() else "READY"), 100
    if not full_text.strip():
        doc.warnings = list(doc.warnings) + ["No text could be extracted - this document cannot be searched."]
    db.commit()


def reconcile_vectors() -> int:
    """Self-healing: documents flagged as indexed whose vectors are gone (wiped Qdrant volume / ephemeral disk / new cluster) are re-queued."""
    if not settings.dense_enabled:
        return 0
    store = get_vector_store()
    db = SessionLocal()
    n = 0
    try:
        for doc in db.scalars(select(Document).where(Document.status == "READY", Document.indexed.is_(True))):
            try:
                if store.count_document(doc.id) < doc.n_chunks:
                    doc.indexed = False
                    n += 1
            except Exception as exc:
                log.warning("vector reconcile failed: %s", exc)
                break
        db.commit()
    finally:
        db.close()
    if n:
        log.warning("%d document(s) were missing vectors and will be re-indexed", n)
    return n


def backfill_vectors() -> int:
    """Index documents that became READY before the embedding models finished loading."""
    n = 0
    emb = get_embeddings()
    db = SessionLocal()
    try:
        for doc in db.scalars(select(Document).where(Document.status == "READY", Document.indexed.is_(False))):
            rows = list(db.scalars(select(DocChunk).where(DocChunk.document_id == doc.id).order_by(DocChunk.chunk_index)))
            if not rows:
                continue
            chunks = [Chunk(id=r.id, doc_id=doc.id, doc_name=doc.filename, idx=r.chunk_index, page=r.page_number, start=r.start_char,
                            end=r.end_char, section=r.section, text=r.text, ocr_conf=r.ocr_conf, paged=doc.paged, doc_date=doc.doc_date) for r in rows]
            try:
                doc.indexed = index_document(db, doc, chunks, emb)
                db.commit()
                n += int(doc.indexed)
            except Exception as exc:
                db.rollback()
                log.warning("backfill failed for %s: %s", doc.id, exc)
        if n:
            for sid in {d for (d,) in db.execute(select(Document.session_id).distinct())}:
                corpus_cache.bump(sid)
    finally:
        db.close()
    return n


# ------------------------------------------------------------------------------------------------
# management
# ------------------------------------------------------------------------------------------------
def delete_document(db: Session, doc: Document) -> None:
    sid = doc.session_id
    try:
        if settings.dense_enabled:
            get_vector_store().delete_document(doc.id)
    except Exception as exc:
        log.warning("vector delete failed for %s: %s", doc.id, exc)
    p = file_path(doc)
    db.delete(doc)
    db.commit()
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
    corpus_cache.bump(sid)


def purge_old_documents(days: int) -> int:
    """Delete documents uploaded more than `days` days ago (all sessions). Returns how many were removed."""
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    with SessionLocal() as db:
        for doc in list(db.scalars(select(Document).where(Document.uploaded_at < cutoff))):
            delete_document(db, doc)
            removed += 1
    if removed:
        log.info("retention: removed %d document(s) older than %d days", removed, days)
    return removed


def set_doc_date(db: Session, doc: Document, iso: str | None) -> Document:
    if iso and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", iso):
        raise IngestError("Date must look like YYYY, YYYY-MM or YYYY-MM-DD.")
    doc.doc_date = iso or None
    doc.doc_date_source = "set manually" if iso else None
    db.commit()
    corpus_cache.bump(doc.session_id)
    return doc
