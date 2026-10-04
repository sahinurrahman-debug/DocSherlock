"""The Evidence Pack PDF: complete, checkable, safe against hostile document text, and private to its owner."""
import copy

import pymupdf
from conftest import Api

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.investigation import Question


def pack(api, qid):
    r = api.get(f"/api/questions/{qid}/pack")
    assert r.status_code == 200, r.text
    return r


def text_of(r):
    doc = pymupdf.open("pdf", r.content)
    return doc, "\n".join(p.get_text() for p in doc)


def test_pack_for_a_conflict_answer_contains_everything_a_reviewer_needs(demo_api):
    res = demo_api.ask("What are the payment terms?")
    demo_api.post(f"/api/questions/{res['id']}/challenge", json={"use_llm": False})
    r = pack(demo_api, res["id"])
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert f'DocSherlock_evidence_{res["id"]}.pdf' in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    doc, text = text_of(r)
    assert len(doc) >= 4 and "What are the payment terms?" in text
    assert "Net 30" in text and "Net 45" in text and "CONFLICTED" in text
    assert "3 of 3 cited quotes were compared with the stored page text" in text and "all match exactly" in text
    assert "Red-team review" in text and "SURVIVED" in text
    assert "Inference, not stated in the documents" in text, "the resolution is labelled as inference"
    assert "page 1 of" in text.replace("\n", " ") and doc.metadata["author"] == "DocSherlock"
    # the original PDF page is embedded, with the cited passage marked
    assert any(len(p.get_images()) for p in doc)
    # fingerprints identify the exact uploaded files
    with SessionLocal() as db:
        for name in ("Vendor_Services_Agreement_2023.pdf", "Contract_Amendment_No1_2024-01-15.docx"):
            d = db.query(Document).filter(Document.filename == name, Document.session_id == demo_api.session).one()
            assert d.sha256 in text.replace("\n", ""), name
    assert "The surrounding text, with the cited passage highlighted" in text                  # Word / e-mail sources get a text excerpt instead of an image


def test_pack_for_a_simple_answer_and_for_a_refusal(demo_api):
    ok = demo_api.ask("What is the liability cap?")
    _, text = text_of(pack(demo_api, ok["id"]))
    assert "$1,000,000" in text and "Appendix A" in text and "Appendix B" in text and "SHA-256" in text
    refusal = demo_api.ask("What is the share price of Northwind?")
    doc, text = text_of(pack(demo_api, refusal["id"]))
    assert refusal["status"] == "insufficient" and "INSUFFICIENT" in text and "0 of 0 cited quotes" in text and len(doc) >= 2


def test_time_scoped_answers_say_so(demo_api):
    res = demo_api.ask("What are the payment terms?", as_of="2023-12-31")
    _, text = text_of(pack(demo_api, res["id"]))
    assert "Answered as of 2023-12-31" in text and "documents that existed by then" in text


def test_hostile_document_text_is_printed_literally_never_interpreted(api):
    evil = "<script>alert(1)</script> <b>Employees</b> receive twenty (20) days of paid annual leave per year & <img src=x onerror=alert(2)>."
    api.add_text("leave policy.txt", "# Leave\n" + evil + "\nDate: 2024-02-01")
    res = api.ask("How many days of paid annual leave do employees receive?")
    _, text = text_of(pack(api, res["id"]))
    assert "<script>alert(1)</script>" in text and "<b>Employees</b>" in text and "&" in text, "markup in documents is shown as text"


def test_the_pack_admits_when_a_stored_quote_no_longer_matches(demo_api):
    res = demo_api.ask("What is the liability cap?")
    with SessionLocal() as db:
        row = db.get(Question, res["id"])
        payload = copy.deepcopy(row.payload)
        payload["citations"][0]["quote"] += " (altered)"
        row.payload = payload
        db.commit()
    _, text = text_of(pack(demo_api, res["id"]))
    assert "not all match" in text


def test_cannot_download_someone_elses_pack(client, demo_api):
    res = demo_api.ask("What is the liability cap?")
    assert Api(client, "pack-stranger-session").get(f"/api/questions/{res['id']}/pack").status_code == 404
    assert demo_api.get("/api/questions/doesnotexist/pack").status_code == 404


def test_the_cover_carries_the_same_logo_as_the_app(demo_api):
    res = demo_api.ask("What is the share price of Northwind?")                 # a refusal has no page images, so any image on page 1 is the logo
    doc, _ = text_of(pack(demo_api, res["id"]))
    images = doc[0].get_images()
    assert len(images) == 1
    pix = pymupdf.Pixmap(doc, images[0][0])
    assert (pix.width, pix.height) == (160, 160) and pix.pixel(8, 80)[:3] == (31, 111, 104)      # the brand tile, #1f6f68, rendered from public/favicon.svg
