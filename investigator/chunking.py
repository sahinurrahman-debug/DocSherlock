"""Section-aware chunking. Chunks never cross a heading and always map back to exact page offsets."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Chunk, PageText
from .textutil import split_sentences

TARGET = 650
MAX_CHARS = 1100
MIN_TAIL = 140

_NUMBERED = re.compile(r"^(?:section\s+)?(?:\d+(?:\.\d+){0,3}|[IVX]{1,6}|[A-Z])[.)]?\s+[A-Z][^.!?]{2,80}$")
_ARTICLE = re.compile(r"^(?:article|section|clause|chapter|part|appendix|annex|schedule|exhibit)\s+[\dIVXA-Z]+\b.{0,70}$", re.I)


def heading_text(line: str) -> str | None:
    s = line.strip()
    if not s:
        return None
    if s.startswith("#"):
        return s.lstrip("#").strip() or None
    if len(s) > 85 or s.endswith((".", ",", ";")) or "|" in s:
        return None
    if _ARTICLE.match(s) or _NUMBERED.match(s):
        return s
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and s.upper() == s and len(s.split()) <= 9:
        return s.title()
    if s.endswith(":") and len(s.split()) <= 6:
        return s.rstrip(":")
    return None


@dataclass
class _Unit:
    start: int
    end: int
    heading: str | None = None      # set => heading unit


def _units(text: str) -> list[_Unit]:
    out: list[_Unit] = []
    pos = 0
    for line in text.split("\n"):
        ls = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        h = heading_text(line)
        if h is not None and (line.lstrip().startswith("#") or len(line.split()) <= 12):
            a = ls + (len(line) - len(line.lstrip()))
            out.append(_Unit(a, ls + len(line.rstrip()), heading=h))
            continue
        for a, b in split_sentences(line):
            out.append(_Unit(ls + a, ls + b))
    return out


def chunk_document(doc_id: str, doc_name: str, pages: list[PageText], paged: bool, doc_date: str | None,
                   doc_title: str | None = None) -> list[Chunk]:
    chunks: list[Chunk] = []
    section = doc_title or ""
    idx = 0

    for page in pages:
        text = page.text
        if not text.strip():
            continue
        units = _units(text)
        cur: list[_Unit] = []
        cur_len = 0

        def flush():
            nonlocal cur, cur_len, idx
            if not cur:
                return
            start, end = cur[0].start, cur[-1].end
            body = text[start:end]
            if chunks and len(body) < MIN_TAIL and chunks[-1].page == page.number and chunks[-1].section == section \
                    and chunks[-1].end <= start and len(chunks[-1].text) + len(body) < MAX_CHARS + MIN_TAIL:
                prev = chunks[-1]
                prev.end = end
                prev.text = text[prev.start:end]
            else:
                chunks.append(Chunk(id=f"{doc_id}:{idx}", doc_id=doc_id, doc_name=doc_name, idx=idx, page=page.number,
                                    start=start, end=end, section=section, text=body, ocr_conf=page.ocr_conf, paged=paged,
                                    doc_date=doc_date))
                idx += 1
            cur, cur_len = [], 0

        for u in units:
            if u.heading is not None:
                flush()
                section = u.heading
                continue
            ulen = u.end - u.start
            if cur and (cur_len + ulen > MAX_CHARS or cur_len >= TARGET):
                flush()
            cur.append(u)
            cur_len += ulen + 1
        flush()
    return chunks
