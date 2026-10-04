"""PostgreSQL compatibility.

* `test_ddl_compiles_for_postgresql` always runs: every table compiles to valid PostgreSQL DDL with sensible column types.
* `test_live_postgres_roundtrip` runs only when TEST_DATABASE_URL points at a real PostgreSQL (e.g. the docker-compose `db` service):
      TEST_DATABASE_URL=postgresql+psycopg://docsherlock:docsherlock@localhost:5432/docsherlock_test pytest tests/test_postgres.py
"""
import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.config import Settings
from app.core.database import Base
from app import models  # noqa: F401  (register tables)
from app.models.document import Claim, DocChunk, Document, Page
from app.models.investigation import Citation, ConflictRecord, Investigation, Question


def test_ddl_compiles_for_postgresql():
    dialect = postgresql.dialect()
    ddl = {t.name: str(CreateTable(t).compile(dialect=dialect)) for t in Base.metadata.sorted_tables}
    assert set(ddl) >= {"documents", "pages", "chunks", "claims", "embedding_cache", "investigations", "questions", "citations", "conflicts"}
    assert "BYTEA" in ddl["documents"] and "JSON" in ddl["documents"] and "TIMESTAMP WITH TIME ZONE" in ddl["documents"]
    assert "ON DELETE CASCADE" in ddl["pages"] and "ON DELETE CASCADE" in ddl["chunks"] and "ON DELETE CASCADE" in ddl["questions"]
    for t in Base.metadata.sorted_tables:                                    # indexes compile too
        for ix in t.indexes:
            str(CreateIndex(ix).compile(dialect=dialect))


@pytest.mark.parametrize("raw,expected", [
    ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),               # Render / Heroku style
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
])
def test_database_url_normalisation(raw, expected):
    assert Settings(database_url=raw).sqlalchemy_url == expected


def test_psycopg_driver_is_importable():
    import psycopg  # noqa: F401


LIVE = os.environ.get("TEST_DATABASE_URL", "")


@pytest.mark.skipif(not LIVE.startswith("postgresql"), reason="set TEST_DATABASE_URL to a real PostgreSQL to run")
def test_live_postgres_roundtrip():
    eng = create_engine(LIVE, future=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    try:
        with Session(eng) as db:
            doc = Document(id="d1", session_id="s", filename="a.pdf", file_type=".pdf", sha256="x" * 64, file_blob=b"\x00\x01binary", warnings=["w"])
            db.add(doc)
            db.flush()
            page = Page(document_id="d1", page_number=1, text="hello", boxes=[[1, 2, 3, 4, "t", 0.9]])
            db.add(page)
            db.flush()
            db.add(DocChunk(id="d1:0", document_id="d1", session_id="s", page_id=page.id, page_number=1, chunk_index=0, text="hello", start_char=0, end_char=5))
            db.add(Claim(id="d1:0:0", document_id="d1", session_id="s", chunk_id="d1:0", page_number=1, sentence="hello", data={"quantities": [{"value": 1.5}]}))
            inv = Investigation(id="i1", session_id="s")
            q = Question(id="q1", investigation_id="i1", session_id="s", question="?", payload={"a": [1, 2]})
            q.citations.append(Citation(cite_id="S1", document_id="d1"))
            q.conflicts.append(ConflictRecord(data={"positions": []}))
            inv.questions.append(q)
            db.add(inv)
            db.commit()
        with Session(eng) as db:
            d = db.get(Document, "d1")
            assert d.warnings == ["w"] and db.execute(select(Document.file_blob).where(Document.id == "d1")).scalar() == b"\x00\x01binary"
            assert db.get(Claim, "d1:0:0").data["quantities"][0]["value"] == 1.5
            assert db.get(Question, "q1").payload == {"a": [1, 2]}
            db.delete(d)                                                      # cascades to pages, chunks, claims
            db.commit()
            assert db.scalar(text("SELECT count(*) FROM pages")) == 0 and db.scalar(text("SELECT count(*) FROM chunks")) == 0
            assert db.scalar(text("SELECT count(*) FROM claims")) == 0
            db.delete(db.get(Investigation, "i1"))
            db.commit()
            assert db.scalar(text("SELECT count(*) FROM citations")) == 0
    finally:
        Base.metadata.drop_all(eng)
