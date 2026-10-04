"""Runtime configuration (all overridable through environment variables)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("DOCINV_DATA_DIR", ROOT / "data"))
SAMPLES_DIR = ROOT / "samples" / "corpus"

MAX_UPLOAD_MB = float(os.environ.get("DOCINV_MAX_UPLOAD_MB", "40"))
MAX_PDF_PAGES = int(os.environ.get("DOCINV_MAX_PDF_PAGES", "300"))

# Dense embeddings: "auto" uses fastembed when importable, "0" disables (BM25 + char n-grams only).
DENSE = os.environ.get("DOCINV_DENSE", "auto").lower()
DENSE_MODEL = os.environ.get("DOCINV_DENSE_MODEL", "BAAI/bge-small-en-v1.5")

OCR_ENABLED = os.environ.get("DOCINV_OCR", "on").lower() not in {"0", "off", "false", "no"}

# LLM synthesis (optional). Without a key the deterministic extractive engine is used.
LLM_MODEL = os.environ.get("DOCINV_MODEL", "claude-opus-5-5")
LLM_EFFORT = os.environ.get("DOCINV_EFFORT", "medium")
LLM_TIMEOUT_S = float(os.environ.get("DOCINV_LLM_TIMEOUT", "90"))


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".xlsx",
    ".html", ".htm", ".json", ".eml",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
