"""Claim extraction: typed sentence-level claims (subject + value + date) built by rules at ingest time, persisted, and
re-hydrated into `Fact` objects for conflict detection, comparison and the evidence matrix."""
from __future__ import annotations

from app.domain import Chunk, Fact, Quantity
from app.models.document import Claim
from app.services.facts import build_fact, extract_quantities
from app.utils.text import STOPWORDS, split_sentences, tokenize


def fact_to_dict(f: Fact) -> dict:
    return {
        "id": f.id, "chunk_id": f.chunk_id, "page": f.page, "paged": f.paged, "section": f.section, "sentence": f.sentence,
        "start": f.start, "end": f.end, "stems": sorted(f.stems), "heading_stems": sorted(f.heading_stems),
        "qualifiers": sorted(f.qualifiers), "negations": f.negations, "tabular": f.tabular,
        "quantities": [{"kind": q.kind, "value": q.value, "unit": q.unit, "raw": q.raw, "start": q.start, "end": q.end,
                        "ctx": sorted(q.ctx), "anchor": q.anchor, "stative": q.stative, "scope_date": q.scope_date} for q in f.quantities],
    }


def fact_from_dict(d: dict, *, doc_id: str, doc_name: str, doc_date: str | None, doc_title: str | None, ocr_conf: float | None) -> Fact:
    qs = [Quantity(kind=q["kind"], value=q["value"], unit=q["unit"], raw=q["raw"], start=q["start"], end=q["end"], ctx=frozenset(q["ctx"]),
                   anchor=q["anchor"], stative=q["stative"], scope_date=q["scope_date"]) for q in d["quantities"]]
    return Fact(id=d["id"], doc_id=doc_id, doc_name=doc_name, chunk_id=d["chunk_id"], page=d["page"], paged=d["paged"], section=d["section"],
                sentence=d["sentence"], start=d["start"], end=d["end"], quantities=qs, stems=frozenset(d["stems"]),
                heading_stems=frozenset(d["heading_stems"]), qualifiers=frozenset(d["qualifiers"]), negations=d["negations"],
                ocr_conf=ocr_conf, doc_date=doc_date, doc_title=doc_title, tabular=d["tabular"])


def extract_claims(chunks: list[Chunk], doc_title: str | None) -> list[Fact]:
    facts: list[Fact] = []
    for ch in chunks:
        for i, (a, b) in enumerate(split_sentences(ch.text)):
            s = ch.text[a:b]
            if s.lstrip().startswith("#") or len(s) < 15:
                continue
            f = build_fact(f"{ch.id}:{i}", ch, a, b, s, ch.section, doc_title)
            if f:
                facts.append(f)
    return facts


def subject_text(f: Fact, limit: int = 6) -> str:
    """Readable subject of a claim: the first few content words outside the value spans."""
    chars = list(f.sentence)
    for q in f.quantities:
        for i in range(q.start, min(q.end, len(chars))):
            chars[i] = " "
    out: list[str] = []
    for t in tokenize("".join(chars)):
        if t in STOPWORDS or len(t) < 3 or t.isdigit() or t in out:
            continue
        out.append(t)
        if len(out) >= limit:
            break
    return " ".join(out)


def claim_row(f: Fact, session_id: str) -> Claim:
    primary = next((q for q in f.quantities if q.kind != "number"), f.quantities[0] if f.quantities else None)
    return Claim(id=f.id, document_id=f.doc_id, session_id=session_id, chunk_id=f.chunk_id, page_number=f.page, section=f.section,
                 sentence=f.sentence, subject=subject_text(f), kind=primary.kind if primary else "statement",
                 value_text=primary.raw if primary else "", data=fact_to_dict(f))


def quantities_of(sentence: str) -> list[Quantity]:
    return extract_quantities(sentence)
