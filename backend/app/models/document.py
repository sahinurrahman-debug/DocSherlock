"""Documents, pages, chunks, claims and the embedding cache."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="UPLOADED", index=True)   # see app.services.ingestion.STAGES
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    n_pages: Mapped[int] = mapped_column(Integer, default=0)
    paged: Mapped[bool] = mapped_column(Boolean, default=True)
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    n_claims: Mapped[int] = mapped_column(Integer, default=0)
    n_chars: Mapped[int] = mapped_column(Integer, default=0)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    doc_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    doc_date_source: Mapped[str | None] = mapped_column(String(48), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)          # dense + sparse vectors written to Qdrant
    file_blob: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))

    pages: Mapped[list["Page"]] = relationship(back_populates="document", cascade="all, delete-orphan", order_by="Page.page_number")

    __table_args__ = (Index("ix_documents_session_sha", "session_id", "sha256"),)


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    section: Mapped[str | None] = mapped_column(String(300), nullable=True)         # first section heading on the page
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str] = mapped_column(String(16), default="text")
    boxes: Mapped[list] = mapped_column(JSON, default=list)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped[Document] = relationship(back_populates="pages")


class DocChunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)                    # "<document_id>:<index>"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=True)
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    section: Mapped[str] = mapped_column(String(300), default="")
    start_char: Mapped[int] = mapped_column(Integer)
    end_char: Mapped[int] = mapped_column(Integer)
    ocr_conf: Mapped[float | None] = mapped_column(Float, nullable=True)


class Claim(Base):
    """A typed, sentence-level claim (subject + value) used for conflict detection and the evidence matrix."""
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_id: Mapped[str] = mapped_column(String(64), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(300), default="")
    sentence: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(300), default="")
    kind: Mapped[str] = mapped_column(String(16), default="")           # money | percent | duration | date | number | statement
    value_text: Mapped[str] = mapped_column(String(300), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)               # full Fact (quantities, stems, qualifiers ...)


class EmbeddingCache(Base):
    __tablename__ = "embedding_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)       # sha1(model + text)
    vec: Mapped[bytes] = mapped_column(LargeBinary)
