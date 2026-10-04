"""The real retrieval stack: FastEmbed dense + sparse vectors in Qdrant, tenant filtering, cross-encoder reranking.
Loads the actual models (cached locally after the first run), so these are marked `slow`."""
import pytest
from conftest import Api

from app.core.config import settings
from app.services import embeddings as emb_mod
from app.services.vectorstore import get_vector_store

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def stack(client):
    """Switch the process to the dense stack for this module only."""
    old = (settings.dense_enabled, settings.rerank_enabled, emb_mod._service)
    settings.dense_enabled = settings.rerank_enabled = True
    svc = emb_mod.EmbeddingService()
    emb_mod._service = svc
    svc.warmup(blocking=True)
    assert svc.ready and svc.sparse_ready and svc.rerank_ready, svc.status()
    yield svc
    settings.dense_enabled, settings.rerank_enabled, emb_mod._service = old


def test_documents_are_indexed_into_qdrant_and_removed_with_them(client, stack):
    a = Api(client, "hybrid-session-A1")
    before = get_vector_store().count(a.session)
    d = a.add_text("leave.txt", "# Leave\nEmployees receive twenty (20) days of paid annual leave per calendar year.")
    assert d["status"] == "READY" and a.docs()[0]["indexed"] is True
    assert get_vector_store().count(a.session) == before + d["n_chunks"]
    a.delete(f"/api/documents/{d['id']}")
    assert get_vector_store().count(a.session) == before


def test_semantic_retrieval_finds_paraphrases_the_keywords_miss(client, stack, monkeypatch):
    monkeypatch.setattr(settings, "final_k", 1)          # fewer slots than candidates => the cross-encoder reranks
    a = Api(client, "hybrid-session-B1")
    a.add_text("handbook.txt", "# Time off\nStaff members are entitled to twenty days of vacation every year.")
    a.add_text("it.txt", "# Network\nThe office wifi password is rotated every 90 days by the IT team.")
    res = a.ask("How much holiday do employees get?")
    assert res["trace"]["hits"][0]["doc"] == "handbook.txt"
    assert {"qdrant-dense", "cross-encoder"} <= set(res["trace"]["channels"])        # no shared words => the sparse channel stays silent
    assert res["trace"]["dense"] is True
    res = a.ask("How often is the wifi password rotated?")
    assert res["trace"]["hits"][0]["doc"] == "it.txt" and "qdrant-bm25" in res["trace"]["channels"]


def test_qdrant_filters_isolate_sessions_and_document_scope(client, stack):
    a, b = Api(client, "hybrid-session-C1"), Api(client, "hybrid-session-D1")
    da = a.add_text("alpha.txt", "# Budget\nThe alpha project budget is $5 million for next year.")
    b.add_text("beta.txt", "# Budget\nThe beta project budget is $7 million for next year.")
    ra = a.ask("What is the project budget?")
    assert {h["doc"] for h in ra["trace"]["hits"]} == {"alpha.txt"} and ra["headline"] == "$5 million"
    rb = b.ask("What is the project budget?")
    assert {h["doc"] for h in rb["trace"]["hits"]} == {"beta.txt"}
    a.add_text("gamma.txt", "# Budget\nThe gamma project budget is $9 million for next year.")
    scoped = a.ask("What is the project budget?", document_ids=[da["id"]])
    assert {h["doc"] for h in scoped["trace"]["hits"]} == {"alpha.txt"}


def test_vectors_are_backfilled_for_documents_uploaded_before_the_models_were_ready(client, stack):
    """Simulate the cold-start race: a READY document without vectors gets indexed by the backfill job."""
    from app.core.database import SessionLocal
    from app.models.document import Document
    from app.services import ingestion

    a = Api(client, "hybrid-session-E1")
    d = a.add_text("late.txt", "# Notice\nThe notice period for resignation is thirty (30) days.")
    db = SessionLocal()
    try:
        doc = db.get(Document, d["id"])
        get_vector_store().delete_document(doc.id)
        doc.indexed = False
        db.commit()
    finally:
        db.close()
    n = ingestion.backfill_vectors()
    assert n >= 1 and a.docs()[0]["indexed"] is True
    assert a.ask("What is the notice period for resignation?")["trace"]["dense"] is True


def test_dense_active_answers_still_abstain_on_unrelated_questions(client, stack):
    a = Api(client, "hybrid-session-F1")
    a.add_text("pol.txt", "# Passwords\nPasswords must be rotated every 90 days.")
    res = a.ask("What is the airspeed velocity of an unladen swallow?")
    assert res["status"] == "insufficient" and res["level"] == "INSUFFICIENT"


def test_reconcile_requeues_documents_whose_vectors_vanished(client, stack):
    """Ephemeral Qdrant (wiped volume / new cluster) must self-heal instead of silently degrading to keyword search."""
    from app.services import ingestion

    a = Api(client, "hybrid-session-G1")
    d = a.add_text("wiped.txt", "# Notice\nThe notice period for resignation is thirty (30) days.")
    assert a.docs()[0]["indexed"] is True
    get_vector_store().delete_document(d["id"])                          # the vectors disappear, the database row survives
    assert ingestion.reconcile_vectors() >= 1 and a.docs()[0]["indexed"] is False
    assert ingestion.backfill_vectors() >= 1 and a.docs()[0]["indexed"] is True
    assert get_vector_store().count_document(d["id"]) == d["n_chunks"]
