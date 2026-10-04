"""HTTP API: sessions, multi-upload + status stages, viewer endpoints, investigations, evidence, SSE, report export."""
import json
import time

import pytest
from conftest import Api
from test_extract import make_pdf, render_text_png

from app.core.config import settings
from app.services import ingestion, ocr


# ---- upload / documents ------------------------------------------------------------------------
def test_multi_upload_mixed_formats_and_bad_files(api):
    body = api.upload(("a.txt", b"Invoices are payable Net 30 from the invoice date."),
                      ("b.pdf", make_pdf(["Invoices are payable Net 45 from the invoice date."])),
                      ("virus.exe", b"MZ"), ("broken.pdf", b"%PDF-1.4 nope"), ("fake.pdf", b"this is not a pdf"), ("empty.txt", b""))
    ok = {r["filename"]: r["ok"] for r in body["results"]}
    assert ok == {"a.txt": True, "b.pdf": True, "virus.exe": False, "broken.pdf": True, "fake.pdf": False, "empty.txt": False}
    assert "Unsupported" in next(r for r in body["results"] if r["filename"] == "virus.exe")["error"]
    assert "PDF" in next(r for r in body["results"] if r["filename"] == "fake.pdf")["error"]
    by = {d["filename"]: d for d in body["documents"]}
    assert by["a.txt"]["status"] == "READY" and by["b.pdf"]["status"] == "READY"
    assert by["broken.pdf"]["status"] == "FAILED" and "PDF" in by["broken.pdf"]["error"]       # corrupt content is reported, not silently dropped
    assert len(api.conflicts()) == 1


def test_duplicate_upload_is_detected_and_same_name_gets_suffix(api):
    api.upload(("a.txt", b"first version of the policy text here"))
    dup = api.upload(("a.txt", b"first version of the policy text here"))["results"][0]
    assert dup["duplicate"] is True and "Identical" in dup["message"] and len(api.docs()) == 1
    api.upload(("a.txt", b"a different second version of the text"))
    assert [d["filename"] for d in api.docs()] == ["a.txt", "a (2).txt"]


def test_failed_document_can_be_retried_by_reuploading(api):
    api.upload(("x.pdf", b"%PDF-1.4 broken"))
    assert api.docs()[0]["status"] == "FAILED"
    api.upload(("x.pdf", b"%PDF-1.4 broken"))
    assert len(api.docs()) == 1                       # the failed record was replaced, not duplicated


def test_document_status_progress_and_metadata(api):
    d = api.add_text("pol.txt", "# Policy\nPasswords must be rotated every 90 days.\nMFA is mandatory for remote access.")
    assert d["status"] == "READY" and d["progress"] == 100 and d["n_chunks"] >= 1 and d["n_claims"] >= 1
    claims = api.get(f"/api/documents/{d['id']}/claims").json()
    assert any(c["kind"] == "duration" and c["value"] == "90 days" for c in claims)
    assert api.get("/api/documents/nope").status_code == 404


def test_async_ingestion_reports_stages_and_finishes(api, monkeypatch):
    monkeypatch.setattr(settings, "ingest_mode", "async")
    r = api.c.post("/api/documents/upload", files=[("files", ("a.txt", b"# Policy\nPasswords must be rotated every 90 days.", "text/plain"))], headers=api.h)
    assert r.status_code == 202
    seen = set()
    deadline = time.time() + 60
    while time.time() < deadline:
        d = api.docs()[0]
        seen.add(d["status"])
        if d["status"] in ("READY", "FAILED"):
            break
        time.sleep(0.05)
    assert d["status"] == "READY", d
    assert seen <= set(ingestion.STAGES) and "READY" in seen


def test_sessions_are_isolated(client):
    a, b = Api(client, "iso-session-A1"), Api(client, "iso-session-B1")
    doc = a.add_text("secret.txt", "The merger budget is $9 million for the project.")
    assert [d["filename"] for d in a.docs()] == ["secret.txt"] and b.docs() == []
    assert b.get(f"/api/documents/{doc['id']}").status_code == 404
    assert b.delete(f"/api/documents/{doc['id']}").status_code == 404
    assert b.ask("What is the merger budget?")["status"] == "insufficient"
    assert a.ask("What is the merger budget?")["headline"] == "$9 million"
    assert client.get("/api/documents", headers={"X-Session-Id": "bad id!"}).status_code == 400


def test_delete_one_and_reset_workspace(api):
    d = api.add_text("a.txt", "some searchable text about invoices and payment")
    assert api.delete(f"/api/documents/{d['id']}").status_code == 204 and api.docs() == []
    api.add_text("b.txt", "another text document with some words")
    assert api.delete("/api/documents").status_code == 204 and api.docs() == []


def test_set_document_date_validation(api):
    d = api.add_text("A.txt", "Total headcount: the company has 142 employees today.")
    assert api.patch(f"/api/documents/{d['id']}", json={"doc_date": "last tuesday"}).status_code == 400
    assert api.patch("/api/documents/nope", json={"doc_date": "2024"}).status_code == 404
    out = api.patch(f"/api/documents/{d['id']}", json={"doc_date": "2023-05"}).json()
    assert out["doc_date"] == "2023-05" and out["doc_date_source"] == "set manually"
    assert api.patch(f"/api/documents/{d['id']}", json={"doc_date": None}).json()["doc_date"] is None


# ---- viewer ------------------------------------------------------------------------------------
def test_page_endpoints_text_pdf_and_file_restore(api):
    d = api.upload(("p.pdf", make_pdf(["Termination requires sixty (60) days written notice."])))["documents"][0]
    page = api.get(f"/api/documents/{d['id']}/pages/1").json()
    text = page["page"]["text"]
    start = text.index("Termination")
    img = api.get(f"/api/documents/{d['id']}/pages/1/image", params={"start": start, "end": len(text)})
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG"
    assert api.get(f"/api/documents/{d['id']}/pages/9").status_code == 404
    assert api.get(f"/api/documents/{d['id']}/file").status_code == 200
    # simulate an ephemeral disk (Render): wipe the upload, the copy kept in the database restores it
    (settings.upload_dir / api.session / f"{d['id']}.pdf").unlink()
    assert api.get(f"/api/documents/{d['id']}/file").status_code == 200
    assert api.get(f"/api/documents/{d['id']}/pages/1/image").status_code == 200


@pytest.mark.skipif(not ocr.available(), reason="OCR engine not installed")
def test_image_upload_ocr_answer_and_highlight(api):
    api.upload(("scan.png", render_text_png("Headcount is 128 employees")))
    doc = api.docs()[0]
    assert doc["ocr_used"] and doc["ocr_conf"] > 0.8 and doc["status"] == "READY"
    res = api.ask("How many employees are there?")
    assert res["status"] == "answered" and res["headline"] == "128 employees"
    c = res["citations"][0]
    img = api.get(f"/api/documents/{c['doc_id']}/pages/1/image", params={"start": c["start"], "end": c["end"]})
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    t = api.add_text("t.txt", "plain text document")
    assert api.get(f"/api/documents/{t['id']}/pages/1/image").status_code == 415      # text documents have no page image


# ---- investigations / questions / evidence ----------------------------------------------------------
def test_investigation_history_pin_note_and_report(api):
    api.add_text("A.txt", "# Payment Terms\nInvoices are payable Net 30 from the invoice date.")
    api.add_text("B.txt", "# Payment Terms\nInvoices are payable Net 45 from the invoice date.")
    q1 = api.ask("What are the payment terms?")
    inv_id = q1["investigation_id"]
    q2 = api.ask("Who is the CFO?", investigation_id=inv_id)
    assert q2["investigation_id"] == inv_id
    invs = api.get("/api/investigations").json()
    assert len(invs) == 1 and invs[0]["n_questions"] == 2 and invs[0]["name"].startswith("What are the payment terms")
    detail = api.get(f"/api/investigations/{inv_id}").json()
    assert [q["question"] for q in detail["questions"]] == ["What are the payment terms?", "Who is the CFO?"]
    assert detail["questions"][0]["level"] == "CONFLICTED" and detail["questions"][1]["level"] == "INSUFFICIENT"

    assert api.patch(f"/api/questions/{q1['id']}", json={"pinned": True, "note": "Ask procurement"}).json()["pinned"] is True
    got = api.get(f"/api/questions/{q1['id']}").json()
    assert got["note"] == "Ask procurement" and got["answer"] == q1["answer"]
    ev = api.get(f"/api/evidence/{q1['id']}").json()
    assert {m["value"] for m in ev["evidence_matrix"]} == {"Net 30", "Net 45"} and ev["level"] == "CONFLICTED"
    cf = api.get(f"/api/conflicts/{q1['id']}").json()
    assert cf["conflict_detected"] and cf["conflicts"][0]["positions"]

    md = api.get(f"/api/investigations/{inv_id}/report")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    assert "SOURCES CONFLICT" in md.text and "Ask procurement" in md.text and "Net 30" in md.text and "DocSherlock" in md.text
    pinned = api.get(f"/api/investigations/{inv_id}/report", params={"pinned_only": True}).text
    assert "Who is the CFO?" not in pinned and "What are the payment terms?" in pinned

    assert api.patch(f"/api/investigations/{inv_id}", json={"name": "Vendor review"}).json()["name"] == "Vendor review"
    assert api.delete(f"/api/investigations/{inv_id}").status_code == 204
    assert api.get(f"/api/investigations/{inv_id}").status_code == 404 and api.get(f"/api/questions/{q1['id']}").status_code == 404


def test_create_investigation_explicitly_and_use_it(api):
    inv = api.post("/api/investigations", json={"name": "Case 17"}).json()
    api.add_text("pol.txt", "# Passwords\nPasswords must be rotated every 90 days.")
    res = api.ask("How often must passwords be rotated?", investigation_id=inv["id"])
    assert res["investigation_id"] == inv["id"]
    assert api.ask("q", investigation_id="does-not-exist") if False else api.post("/api/questions", json={"question": "q", "investigation_id": "nope"}).status_code == 404


def test_sse_stream_emits_stages_then_result(api):
    api.add_text("pol.txt", "# Passwords\nPasswords must be rotated every 90 days.")
    with api.c.stream("POST", "/api/questions/stream", json={"question": "How often must passwords be rotated?", "mode": "rules"}, headers=api.h) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events, name = [], None
        for line in r.iter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((name, json.loads(line.split(":", 1)[1])))
    kinds = [e[0] for e in events]
    assert kinds[0] == "investigation" and kinds[-1] == "result" and "stage" in kinds
    stages = [e[1]["stage"] for e in events if e[0] == "stage"]
    assert stages[:2] == ["retrieving", "checking_conflicts"] and stages[-1] == "verifying"
    assert events[-1][1]["headline"] == "90 days"


def test_sse_stream_reports_errors(api):
    with api.c.stream("POST", "/api/questions/stream", json={"question": "q", "investigation_id": "nope"}, headers=api.h) as r:
        body = "".join(r.iter_text())
    assert "event: error" in body and "Investigation not found" in body


def test_request_validation(api):
    assert api.post("/api/questions", json={"question": "q", "mode": "weird"}).status_code == 422
    assert api.post("/api/questions", json={}).status_code == 422
    assert api.post("/api/compare", json={"document_a": "x", "document_b": "x"}).status_code == 400


def test_health_and_openapi(client):
    h = client.get("/api/health").json()
    assert h["status"] == "healthy" and ".pdf" in h["formats"] and h["models"]["dense"]["enabled"] is False
    spec = client.get("/openapi.json").json()
    for path in ("/api/documents/upload", "/api/documents", "/api/questions", "/api/questions/stream", "/api/investigations", "/api/conflicts",
                 "/api/conflicts/{question_id}", "/api/evidence/{question_id}", "/api/compare", "/health"):
        assert path in spec["paths"], path
