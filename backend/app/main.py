"""DocSherlock API - evidence-grounded document investigation."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import conflicts, documents, health, investigations, questions, trustlab
from app.core.config import settings
from app.core.database import init_db

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("docsherlock")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services import ingestion
    from app.services.embeddings import get_embeddings

    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        ingestion.purge_old_documents(settings.retention_days)
    except Exception:
        log.exception("retention purge skipped")
    emb = get_embeddings()
    try:
        ingestion.reconcile_vectors()                          # re-queue documents whose vectors disappeared (ephemeral disk, new Qdrant)
    except Exception:
        log.exception("vector reconcile skipped")
    emb.on_ready.append(ingestion.backfill_vectors)           # index documents uploaded while the models were still loading
    emb.warmup()                                              # background thread - the API is available immediately
    log.info("DocSherlock %s started (llm=%s, vector store via %s)", __version__, settings.llm_available, "server" if settings.qdrant_url else "embedded Qdrant")
    yield


app = FastAPI(title="DocSherlock API", version=__version__, lifespan=lifespan,
              description="Evidence-grounded document investigation: multi-format ingestion + OCR, hybrid retrieval (Qdrant), Groq LLM with "
                          "verified citations, conflict detection and uncertainty levels. All data is scoped by the `X-Session-Id` header.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])
for r in (health.router, documents.router, questions.router, investigations.router, conflicts.router, trustlab.router):
    app.include_router(r)

# Single-service deployment: serve the built React app (frontend/dist) from the API when it exists.
_dist = settings.frontend_dist
if _dist.exists() and (_dist / "index.html").exists():
    if (_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/") or path in ("docs", "openapi.json", "redoc", "health"):
            raise HTTPException(404)
        f = (_dist / path).resolve()
        if path and f.is_file() and _dist.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
