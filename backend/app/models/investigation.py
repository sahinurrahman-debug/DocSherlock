"""Investigations (cases), the questions asked in them, their citations and recorded conflicts."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.document import utcnow


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200), default="Untitled investigation")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    questions: Mapped[list["Question"]] = relationship(back_populates="investigation", cascade="all, delete-orphan",
                                                      order_by="Question.created_at")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    effective_question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    headline: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="")                 # answered | partial | conflict | insufficient
    level: Mapped[str] = mapped_column(String(16), default="")                  # HIGH | MEDIUM | LOW | CONFLICTED | INSUFFICIENT
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    conflict_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    engine: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)                   # the full response (matrix, trace, caveats ...)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigation: Mapped[Investigation] = relationship(back_populates="questions")
    citations: Mapped[list["Citation"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    conflicts: Mapped[list["ConflictRecord"]] = relationship(back_populates="question", cascade="all, delete-orphan")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    cite_id: Mapped[str] = mapped_column(String(8))                              # S1, S2 ...
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    document_name: Mapped[str] = mapped_column(String(255), default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str] = mapped_column(String(300), default="")
    chunk_id: Mapped[str] = mapped_column(String(64), default="")
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    quote: Mapped[str] = mapped_column(Text, default="")
    start_char: Mapped[int] = mapped_column(Integer, default=0)
    end_char: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(12), default="support")             # support | conflict | lead
    side: Mapped[str | None] = mapped_column(String(2), nullable=True)

    question: Mapped[Question] = relationship(back_populates="citations")


class ConflictRecord(Base):
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[str] = mapped_column(String(32), default="")
    claim_a: Mapped[str] = mapped_column(Text, default="")
    claim_b: Mapped[str] = mapped_column(Text, default="")
    source_a: Mapped[str] = mapped_column(String(400), default="")
    source_b: Mapped[str] = mapped_column(String(400), default="")
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    data: Mapped[dict] = mapped_column(JSON, default=dict)                        # the full disputed point (positions, resolution)

    question: Mapped[Question] = relationship(back_populates="conflicts")
