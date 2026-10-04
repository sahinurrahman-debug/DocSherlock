"""HTTP API: multi-file upload, error handling, viewer endpoints, notebook + export."""

import pytest
from fastapi.testclient import TestClient

from investigator import ocr
from investigator.app import create_app
from test_extract import make_pdf, render_text_png


@pytest.fixture()
def client(engine):
    return TestClient(create_app(engine))


def up(client, *files):
    return client.post("/api/documents", files=[("files", f) for f in files])


def test_multi_upload_mixed_formats_and_bad_files(client):
    r = up(client, ("a.txt", b"Invoices are payable Net 30 from the invoice date.", "text/plain"),
           ("b.pdf", make_pdf(["Invoices are payable Net 45 from the invoice date."]), "application/pdf"),
           ("virus.exe", b"MZ", "application/octet-stream"),
           ("broken.pdf", b"%PDF-1.4 nope", "application/pdf"),
           ("empty.txt", b"", "text/plain"))
    assert r.status_code == 200
    body = r.json()
    ok = {x["filename"]: x["ok"] for x in body["results"]}
    assert ok == {"a.txt": True, "b.pdf": True, "virus.exe": False, "broken.pdf": False, "empty.txt": False}
    assert len(body["documents"]) == 2 and body["conflicts"] == 1
    assert "Unsupported" in next(x for x in body["results"] if x["filename"] == "virus.exe")["error"]


def test_duplicate_upload_is_detected_and_same_name_gets_suffix(client):
    up(client, ("a.txt", b"first version of the policy text here", "text/plain")).json()
    r2 = up(client, ("a.txt", b"first version of the policy text here", "text/plain")).json()
    assert r2["results"][0]["duplicate"] is True and len(r2["documents"]) == 1
    r3 = up(client, ("a.txt", b"a different second version of the text", "text/plain")).json()
    assert [d["name"] for d in r3["documents"]] == ["a.txt", "a (2).txt"]


def test_ask_flow_and_validation(client):
    up(client, ("pol.txt", b"# Passwords\nPasswords must be rotated every 90 days.", "text/plain"))
    r = client.post("/api/ask", json={"question": "How often must passwords be rotated?"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "answered" and body["headline"] == "90 days"
    assert client.post("/api/ask", json={"question": "   "}).status_code == 400
    assert client.post("/api/ask", json={"question": "x" * 2500}).status_code == 422
    assert client.post("/api/ask", json={"question": "q", "mode": "weird"}).status_code == 422


def test_page_endpoints_text_pdf_image(client):
    up(client, ("p.pdf", make_pdf(["Termination requires sixty (60) days written notice."]), "application/pdf"))
    doc = client.get("/api/documents").json()["documents"][0]
    page = client.get(f"/api/documents/{doc['id']}/pages/1").json()
    text = page["page"]["text"]
    start = text.index("Termination")
    img = client.get(f"/api/documents/{doc['id']}/pages/1/image", params={"start": start, "end": len(text)})
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{doc['id']}/pages/9").status_code == 404
    assert client.get("/api/documents/nope/pages/1").status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200


@pytest.mark.skipif(not ocr.available(), reason="OCR engine not installed")
def test_image_upload_and_highlight_render(client):
    up(client, ("scan.png", render_text_png("Headcount is 128 employees"), "image/png"))
    doc = client.get("/api/documents").json()["documents"][0]
    assert doc["ocr_used"] and doc["ocr_conf"] > 0.8
    res = client.post("/api/ask", json={"question": "How many employees are there?"}).json()
    assert res["status"] == "answered" and res["headline"] == "128 employees"
    c = res["citations"][0]
    img = client.get(f"/api/documents/{c['doc_id']}/pages/1/image", params={"start": c["start"], "end": c["end"]})
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    # text documents have no page image
    up(client, ("t.txt", b"plain text document", "text/plain"))
    tdoc = next(d for d in client.get("/api/documents").json()["documents"] if d["name"] == "t.txt")
    assert client.get(f"/api/documents/{tdoc['id']}/pages/1/image").status_code == 415


def test_set_document_date_validation_and_conflict_reasoning(client):
    up(client, ("A.txt", b"Total headcount: the company has 142 employees today.", "text/plain"),
       ("B.txt", b"Total headcount: the company has 128 employees today.", "text/plain"))
    docs = client.get("/api/documents").json()["documents"]
    assert client.patch(f"/api/documents/{docs[0]['id']}", json={"doc_date": "last tuesday"}).status_code == 400
    assert client.patch("/api/documents/nope", json={"doc_date": "2024"}).status_code == 404
    client.patch(f"/api/documents/{docs[0]['id']}", json={"doc_date": "2023-01-01"})
    client.patch(f"/api/documents/{docs[1]['id']}", json={"doc_date": "2024-06"})
    c = client.get("/api/conflicts").json()["conflicts"][0]
    assert "B.txt" in c["resolution"]


def test_delete_and_reset(client):
    up(client, ("a.txt", b"some searchable text about invoices", "text/plain"))
    doc = client.get("/api/documents").json()["documents"][0]
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 404
    up(client, ("b.txt", b"another text document with words", "text/plain"))
    assert client.delete("/api/documents").status_code == 200
    assert client.get("/api/documents").json()["documents"] == []


def test_notebook_pin_note_and_markdown_export(client):
    up(client, ("A.txt", b"# Payment Terms\nInvoices are payable Net 30 from the invoice date.", "text/plain"),
       ("B.txt", b"# Payment Terms\nInvoices are payable Net 45 from the invoice date.", "text/plain"))
    res = client.post("/api/ask", json={"question": "What are the payment terms?"}).json()
    assert res["status"] == "conflict"
    note = client.post("/api/notebook", json={"result": res, "comment": "Ask procurement"}).json()
    assert len(client.get("/api/notebook").json()["notes"]) == 1
    md = client.get("/api/notebook/export")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    text = md.text
    assert "SOURCES CONFLICT" in text and "Ask procurement" in text and "Net 30" in text and "Conflict register" in text
    client.delete(f"/api/notebook/{note['id']}")
    assert client.get("/api/notebook").json()["notes"] == []


def test_status_reports_capabilities(client):
    s = client.get("/api/status").json()
    assert s["llm"]["available"] is False and "ocr" in s and ".pdf" in s["formats"]


def test_static_ui_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Document Investigator" in r.text
    assert client.get("/app.js").status_code == 200
