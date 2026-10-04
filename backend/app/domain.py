"""Plain dataclasses shared across the pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class PageText:
    number: int
    text: str
    ocr_conf: float | None = None          # mean OCR confidence 0..1 (None => born-digital text)
    method: str = "text"                    # text | ocr | docx | table ...
    boxes: list[list[Any]] = field(default_factory=list)   # OCR boxes: [x0, y0, x1, y1, text, conf] in image px
    width: int | None = None
    height: int | None = None


@dataclass
class Extracted:
    pages: list[PageText]
    paged: bool = True                      # False => "page" is meaningless (docx/txt/csv): UI shows sections only
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)   # title, email date, ...


@dataclass
class DocumentRecord:
    id: str
    name: str
    ext: str
    sha256: str
    size: int
    n_pages: int
    paged: bool
    ocr_used: bool
    ocr_conf: float | None
    doc_date: str | None
    doc_date_source: str | None
    warnings: list[str]
    added_at: float
    n_chunks: int = 0
    n_facts: int = 0
    n_chars: int = 0
    title: str | None = None
    status: str = "ready"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Chunk:
    id: str
    doc_id: str
    doc_name: str
    idx: int
    page: int
    start: int                  # offsets into the page text
    end: int
    section: str
    text: str
    ocr_conf: float | None
    paged: bool = True
    doc_date: str | None = None

    @property
    def index_text(self) -> str:
        name = re.sub(r"[_\-.]+", " ", self.doc_name.rsplit(".", 1)[0])
        return f"{name}\n{self.section}\n{self.text}" if self.section else f"{name}\n{self.text}"

    def cite_dict(self) -> dict:
        return {
            "chunk_id": self.id, "doc_id": self.doc_id, "doc_name": self.doc_name, "page": self.page if self.paged else None,
            "section": self.section, "start": self.start, "end": self.end,
        }


@dataclass
class Quantity:
    kind: str                   # money | percent | duration | date | number
    value: Any                  # float, or ISO string for dates
    unit: str                   # currency code / 'day' / 'hour' / ''
    raw: str
    start: int
    end: int
    ctx: frozenset = frozenset()     # content stems in the clause around the value (local subject)
    anchor: str = ""                 # head noun attached to the value ("142 employees" -> employe)
    stative: bool = False            # "has/is/totals ..." - states a standing quantity
    scope_date: bool = False         # (dates) a period/as-of date that scopes a statement rather than an event date


@dataclass
class Fact:
    id: str
    doc_id: str
    doc_name: str
    chunk_id: str
    page: int
    paged: bool
    section: str
    sentence: str
    start: int                  # absolute offsets in page text
    end: int
    quantities: list[Quantity]
    stems: frozenset
    heading_stems: frozenset
    qualifiers: frozenset
    negations: int
    ocr_conf: float | None
    doc_date: str | None
    doc_title: str | None = None
    tabular: bool = False


@dataclass
class Citation:
    id: str                     # S1, S2 ...
    doc_id: str
    doc_name: str
    page: int | None
    section: str
    quote: str                  # verbatim supporting sentence(s)
    passage: str                # surrounding chunk text
    start: int
    end: int
    score: float
    ocr_conf: float | None
    doc_date: str | None = None
    chunk_id: str = ""
    verified: bool = True       # quote verified verbatim against the stored passage
    role: str = "support"       # support | conflict | lead (closest passage but NOT an answer)
    side: str | None = None     # for conflicts: 'A' / 'B'

    def to_dict(self) -> dict:
        return asdict(self)
