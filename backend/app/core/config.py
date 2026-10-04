"""Application settings - everything is overridable through environment variables or backend/.env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".xlsx", ".html", ".htm", ".json", ".eml",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DocSherlock"
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- storage ---------------------------------------------------------------------------
    data_dir: Path = BACKEND_DIR / "data"
    upload_dir: Path = BACKEND_DIR / "uploads"
    # PostgreSQL in production (postgresql+psycopg://user:pass@host/db). Falls back to SQLite for zero-setup development.
    database_url: str = ""
    store_file_blobs: bool = True            # keep originals in the database too (survives ephemeral disks, e.g. Render)
    max_blob_mb: float = 25.0

    # ---- vector store (Qdrant) -------------------------------------------------------------
    qdrant_url: str = ""                      # http(s)://host:6333 or a Qdrant Cloud URL. Empty => embedded local mode
    qdrant_api_key: str = ""
    qdrant_collection: str = "docsherlock_chunks"
    qdrant_path: str = ""                     # embedded mode directory (default: <data_dir>/qdrant); ":memory:" for tests

    # ---- retrieval models (FastEmbed, run locally) -----------------------------------------
    dense_enabled: bool = True
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    rerank_enabled: bool = True
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    retrieve_k: int = 24                      # candidates fetched per channel before fusion
    rerank_top: int = 12                      # fused candidates passed to the cross-encoder
    final_k: int = 8                          # chunks handed to evidence selection

    # ---- LLM (Groq is the main answering engine; rule-based engine is the fallback) ----------
    llm_enabled: bool = True
    llm_provider: str = "groq"               # groq | openai_compatible
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "llama-3.3-70b-versatile"
    groq_reasoning_effort: str = "low"       # low | medium | high (gpt-oss models)
    groq_structured: str = "auto"            # auto | strict | json_object
    llm_base_url: str = ""                   # for openai_compatible providers
    llm_api_key: str = ""
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_max_output_tokens: int = 3000
    llm_max_passages: int = 7
    llm_passage_chars: int = 900

    # ---- ingestion -------------------------------------------------------------------------
    max_upload_mb: float = 40.0
    max_pdf_pages: int = 300
    ocr_enabled: bool = True
    ocr_max_side: int = 2600                 # longest image side (px) fed to OCR - smaller = less RAM, slightly lower accuracy
    ocr_threads: int = 0                     # ONNX threads for OCR (0 = library default); 1 uses noticeably less memory
    ocr_render_dpi: int = 200                # resolution scanned PDF pages are rendered at before OCR
    retention_days: int = 0                              # >0: at start-up delete documents older than this (keeps small free databases from filling)
    low_memory: bool = False                 # one switch for 512 MB hosts (free tiers): keyword retrieval, lighter OCR, one worker
    ingest_mode: str = "async"               # async (background worker) | sync (tests)
    ingest_workers: int = 2
    chunk_target_chars: int = 650
    chunk_max_chars: int = 1100

    # ---- serving ---------------------------------------------------------------------------
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"
    host: str = "127.0.0.1"
    port: int = 8000

    @model_validator(mode="after")
    def _low_memory_preset(self):
        if self.low_memory:
            self.dense_enabled = False
            self.rerank_enabled = False
            self.ocr_max_side = min(self.ocr_max_side, 1100)
            self.ocr_threads = 1
            self.ocr_render_dpi = min(self.ocr_render_dpi, 130)
            self.ingest_workers = 1
        return self

    # ---- helpers ---------------------------------------------------------------------------
    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if not url:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{(self.data_dir / 'docsherlock.db').as_posix()}"
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @property
    def llm_key(self) -> str:
        return (self.groq_api_key if self.llm_provider == "groq" else self.llm_api_key).strip()

    @property
    def llm_available(self) -> bool:
        return self.llm_enabled and bool(self.llm_key)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    allowed_extensions: set[str] = Field(default_factory=lambda: set(ALLOWED_EXTENSIONS))
    image_extensions: set[str] = Field(default_factory=lambda: set(IMAGE_EXTENSIONS))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
