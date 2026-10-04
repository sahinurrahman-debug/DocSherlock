"""Test harness: isolated SQLite + in-memory Qdrant, synchronous ingestion, no LLM key, lexical retrieval by default.
Every test runs in its own browser-session id, so tests never see each other's documents (the same isolation users get)."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="docsherlock-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(TMP / 'test.db').as_posix()}", "QDRANT_URL": "", "QDRANT_PATH": ":memory:", "INGEST_MODE": "sync",
    "DENSE_ENABLED": "false", "RERANK_ENABLED": "false", "GROQ_API_KEY": "", "LLM_API_KEY": "", "DATA_DIR": str(TMP),
    "UPLOAD_DIR": str(TMP / "uploads"), "LOG_LEVEL": "WARNING",
})
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).parent))

import pytest                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

from app.main import app                         # noqa: E402


class Api:
    """Thin helper around the TestClient bound to one session id."""

    def __init__(self, client: TestClient, session: str):
        self.c, self.session = client, session
        self.h = {"X-Session-Id": session}

    def upload(self, *files: tuple[str, bytes], expect_ok: bool = True):
        r = self.c.post("/api/documents/upload", files=[("files", (n, b, "application/octet-stream")) for n, b in files], headers=self.h)
        assert r.status_code == 202, r.text
        return r.json()

    def add_text(self, name: str, text: str) -> dict:
        res = self.upload((name, text.encode("utf-8")))["results"][0]
        assert res["ok"], res
        return res["document"]

    def docs(self) -> list[dict]:
        return self.c.get("/api/documents", headers=self.h).json()

    def ask(self, question: str, **kw) -> dict:
        r = self.c.post("/api/questions", json={"question": question, "mode": kw.pop("mode", "rules"), **kw}, headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()

    def conflicts(self, **params) -> list[dict]:
        return self.c.get("/api/conflicts", params=params, headers=self.h).json()["conflicts"]

    def get(self, path: str, **kw):
        return self.c.get(path, headers=self.h, **kw)

    def post(self, path: str, **kw):
        return self.c.post(path, headers=self.h, **kw)

    def patch(self, path: str, **kw):
        return self.c.patch(path, headers=self.h, **kw)

    def delete(self, path: str, **kw):
        return self.c.delete(path, headers=self.h, **kw)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def api(client):
    return Api(client, f"t-{uuid.uuid4().hex[:12]}")


@pytest.fixture(scope="session")
def demo_api(client):
    """The sample corpus, ingested once for the whole run (read-only use)."""
    sys.path.insert(0, str(ROOT / "sample-documents"))
    corpus = ROOT / "sample-documents" / "corpus"
    if not corpus.exists() or len(list(corpus.iterdir())) < 11:
        import generate
        generate.main()
    a = Api(client, "demo-session-0001")
    r = a.post("/api/documents/demo")
    assert r.status_code == 202, r.text
    docs = a.docs()
    assert len(docs) == 11 and all(d["status"] == "READY" for d in docs), [(d["filename"], d["status"], d["error"]) for d in docs]
    return a
