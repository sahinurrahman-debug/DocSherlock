"""Hosted embeddings + remote Qdrant (the 512 MB setup), exercised against in-process fake servers.

Nothing here touches the network or loads a model. The fake Qdrant validates every request body against the official `qdrant-client` models, so a
malformed REST body fails here rather than on a real cluster (it has still not been run against a live Qdrant server - see docs/DEPLOY_RENDER.md).
"""
from __future__ import annotations

import json

import httpx
import numpy as np
import pytest
from conftest import Api

from fakes_remote import DIM, FakeEmbeddingAPI, FakeQdrant, fake_vec

from app.core.config import Settings, settings
from app.services import embeddings as emb_mod
from app.services import vectorstore as vs_mod

@pytest.fixture()
def remote(client, monkeypatch):
    """Point the process at fake hosted-embedding + remote-Qdrant servers (dense search on, local models never loaded)."""
    api, qd = FakeEmbeddingAPI(), FakeQdrant()
    monkeypatch.setattr(emb_mod, "_http_transport", httpx.MockTransport(api))
    monkeypatch.setattr(vs_mod, "_http_transport", httpx.MockTransport(qd))
    for k, v in {"dense_enabled": True, "rerank_enabled": False, "embedding_api_url": "https://embeddings.example/v1/embeddings", "embedding_api_key": "k-test",
                 "embedding_model": "fake-embed", "embedding_dim": DIM, "qdrant_url": "https://qdrant.example:6333", "qdrant_api_key": "qd-test-key"}.items():
        monkeypatch.setattr(settings, k, v)
    old_service, old_store = emb_mod._service, vs_mod._store
    svc = emb_mod.EmbeddingService()
    svc.sparse_m.enabled = False                                 # the BM25 sparse model is a separate, local concern; dense is what is under test
    emb_mod._service = svc
    vs_mod._store = None
    svc.warmup(blocking=True)
    yield api, qd, svc
    emb_mod._service, vs_mod._store = old_service, old_store


# ---- hosted embeddings ---------------------------------------------------------------------------
def test_api_embedder_batches_orders_and_authenticates(remote, monkeypatch):
    api, _, svc = remote
    monkeypatch.setattr(settings, "embedding_api_batch", 2)
    out = svc.embed_docs(["alpha beta", "gamma", "delta epsilon", "zeta", "eta"])
    assert out.shape == (5, DIM) and np.allclose(np.linalg.norm(out, axis=1), 1)
    assert [len(c["input"]) for c in api.calls] == [2, 2, 1]
    assert api.calls[0]["model"] == "fake-embed" and api.calls[0]["dimensions"] == DIM and "task" not in api.calls[0]
    assert api.headers[0]["authorization"] == "Bearer k-test"
    assert np.allclose(out[1], np.array(fake_vec("gamma")) / np.linalg.norm(fake_vec("gamma")))   # reversed server order was restored


def test_jina_urls_get_retrieval_tasks(remote, monkeypatch):
    api, _, _ = remote
    monkeypatch.setattr(settings, "embedding_api_url", "https://api.jina.ai/v1/embeddings")
    svc = emb_mod.EmbeddingService()
    svc.warmup(blocking=True)
    svc.embed_docs(["a passage"])
    svc.embed_query("a question")
    assert [c["task"] for c in api.calls] == ["retrieval.passage", "retrieval.query"]


def test_api_embedder_retries_rate_limits_and_reports_dimension_mismatch(remote, monkeypatch):
    api, _, svc = remote
    monkeypatch.setattr(emb_mod.time, "sleep", lambda s: None)
    api.fail_first = 2
    assert svc.embed_query("hello").shape == (DIM,) and len(api.calls) == 3
    monkeypatch.setattr(settings, "embedding_dim", DIM + 1)
    with pytest.raises(emb_mod.EmbeddingAPIError, match="dimensional"):
        emb_mod.ApiEmbedder().embed(["x"])


def test_low_memory_keeps_semantic_search_when_embeddings_are_hosted():
    s = Settings(low_memory=True, database_url="", embedding_api_url="https://api.jina.ai/v1/embeddings")
    assert s.dense_enabled and not s.rerank_enabled and s.ingest_workers == 1
    assert not Settings(low_memory=True, database_url="").dense_enabled


def test_collection_name_follows_model_and_dimension():
    a = Settings(database_url="", embedding_model="jina-embeddings-v3", embedding_dim=384).collection_name
    b = Settings(database_url="", embedding_model="jina-embeddings-v3", embedding_dim=512).collection_name
    assert a != b and a.endswith("_384") and "jina-embeddings-v3" in a


# ---- remote Qdrant over REST ---------------------------------------------------------------------
def test_documents_are_embedded_remotely_indexed_in_qdrant_and_found_semantically(client, remote):
    api, qd, svc = remote
    a = Api(client, "remote-stack-A")
    d1 = a.add_text("leave.txt", "# Leave\nEmployees receive twenty days of paid vacation every year.")
    d2 = a.add_text("it.txt", "# Network\nThe office wifi password is rotated every ninety days.")
    docs = {d["filename"]: d for d in a.docs()}
    assert docs["leave.txt"]["indexed"] is True and docs["it.txt"]["indexed"] is True
    assert ("PUT", "/collections/" + settings.collection_name) in qd.requests                   # collection created with the model/dim-specific name
    assert sum(len(p) for p in qd.points.values()) == d1["n_chunks"] + d2["n_chunks"]
    assert qd.collections[settings.collection_name]["vectors"]["dense"]["size"] == DIM

    res = a.ask("How many vacation days do employees get?")
    assert res["trace"]["dense"] is True and "qdrant-dense" in res["trace"]["channels"]
    assert any("twenty" in c["quote"].lower() for c in res["citations"]), res["answer"]

    a.delete(f"/api/documents/{d1['id']}")
    assert sum(len(p) for p in qd.points.values()) == d2["n_chunks"]                              # deleted with the document


def test_tenant_isolation_on_the_rest_backend(client, remote):
    _, _, _ = remote
    a, b = Api(client, "remote-stack-T1"), Api(client, "remote-stack-T2")
    a.add_text("a.txt", "# Secret\nProject Nightingale launches in March.")
    store = vs_mod.get_vector_store()
    q = np.array(fake_vec("project nightingale launch"))
    assert store.search_dense(a.session, None, q, 5) and store.search_dense(b.session, None, q, 5) == []


def test_qdrant_outage_degrades_to_keyword_retrieval(client, remote, monkeypatch):
    _, qd, _ = remote
    a = Api(client, "remote-stack-O1")
    a.add_text("pay.txt", "# Payment\nInvoices are payable Net 30 from the invoice date.")
    monkeypatch.setattr(vs_mod, "_http_transport", httpx.MockTransport(lambda r: httpx.Response(503, text="down")))
    vs_mod._store = None
    res = a.ask("What are the payment terms?")
    assert res["status"] in ("answered", "conflicted") and "30" in json.dumps(res)
