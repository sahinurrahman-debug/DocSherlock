from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    file_size: int
    status: str = Field(description="UPLOADED | PROCESSING | EXTRACTING | OCR | CHUNKING | EMBEDDING | INDEXING | READY | FAILED")
    progress: int = Field(description="0-100")
    error: str | None = None
    uploaded_at: datetime
    n_pages: int = 0
    paged: bool = True
    n_chunks: int = 0
    n_claims: int = 0
    ocr_used: bool = False
    ocr_conf: float | None = None
    doc_date: str | None = None
    doc_date_source: str | None = None
    title: str | None = None
    warnings: list[str] = []
    indexed: bool = False


class UploadResult(BaseModel):
    filename: str
    ok: bool
    duplicate: bool = False
    message: str = ""
    error: str | None = None
    document: DocumentOut | None = None


class UploadResponse(BaseModel):
    results: list[UploadResult]
    documents: list[DocumentOut]


class DocumentPatch(BaseModel):
    doc_date: str | None = Field(default=None, description="YYYY, YYYY-MM or YYYY-MM-DD; null clears it")


class PageOut(BaseModel):
    number: int
    text: str
    ocr_conf: float | None = None
    method: str = "text"
    has_image: bool = False


class PageResponse(BaseModel):
    document: DocumentOut
    page: PageOut
    n_pages: int


class ClaimOut(BaseModel):
    id: str
    page: int
    section: str
    sentence: str
    subject: str
    kind: str
    value: str
