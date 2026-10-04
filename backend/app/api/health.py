from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.core import database
from app.core.config import settings
from app.services import ocr
from app.services.embeddings import get_embeddings

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/api/health")
def health():
    emb = get_embeddings()
    try:
        with database.engine.connect() as c:
            c.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    if not settings.dense_enabled:
        qdrant_ok, mode = True, "disabled"                 # keyword-only mode: no vector store is loaded
    else:
        try:
            from app.services.vectorstore import get_vector_store
            qdrant_ok = get_vector_store().healthy()
            mode = get_vector_store().mode
        except Exception:
            qdrant_ok, mode = False, "unavailable"
    ready = db_ok and qdrant_ok
    return {
        "status": "healthy" if ready else "degraded", "service": "docsherlock", "version": __version__,
        "database": {"ok": db_ok, "engine": database.engine.dialect.name},
        "vector_store": {"ok": qdrant_ok, "mode": mode, "collection": settings.qdrant_collection},
        "models": emb.status() | {"loading": emb.loading},
        "ocr": {"available": ocr.available(), "reason": ocr.unavailable_reason() if not ocr.available() else ""},
        "llm": {"available": settings.llm_available, "provider": settings.llm_provider, "model": settings.groq_model if settings.llm_available else None,
                "fallback": "rule-based engine"},
        "formats": sorted(settings.allowed_extensions), "max_upload_mb": settings.max_upload_mb,
    }
