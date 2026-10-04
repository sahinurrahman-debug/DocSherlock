from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuestionIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=1500)
    document_ids: list[str] | None = Field(default=None, description="Restrict the investigation to these documents (default: all READY documents)")
    investigation_id: str | None = Field(default=None, description="Continue an investigation; a new one is created when omitted")
    mode: str = Field(default="auto", pattern="^(auto|llm|rules)$", description="auto = LLM with rule-based fallback; rules = never call the LLM")


class QuestionPatch(BaseModel):
    pinned: bool | None = None
    note: str | None = Field(default=None, max_length=2000)


class Confidence(BaseModel):
    score: float
    label: str
    reasons: list[dict[str, str]] = []


class QuestionOut(BaseModel):
    """Full answer payload. `level` is the public uncertainty classification."""
    model_config = ConfigDict(extra="allow")

    id: str
    investigation_id: str
    question: str
    effective_question: str = ""
    status: str = Field(description="answered | partial | conflict | insufficient")
    level: str = Field(description="HIGH | MEDIUM | LOW | CONFLICTED | INSUFFICIENT")
    headline: str = ""
    answer: str
    confidence: Confidence
    conflict_detected: bool = False
    citations: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    evidence_matrix: list[dict[str, Any]] = []
    caveats: list[str] = []
    missing_terms: list[str] = []
    engine: dict[str, Any] = {}
    trace: dict[str, Any] = {}
    timings_ms: dict[str, int] = {}
    pinned: bool = False
    note: str = ""
    created_at: str | None = None


class InvestigationIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class InvestigationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    n_questions: int = 0


class InvestigationDetail(InvestigationOut):
    questions: list[QuestionOut] = []


class CompareIn(BaseModel):
    document_a: str
    document_b: str
    use_llm: bool = True
