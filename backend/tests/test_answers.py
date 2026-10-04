"""End-to-end answer quality on the sample corpus (rule-based engine, lexical retrieval => fully deterministic)."""
import json

import pytest
from conftest import ROOT

QUESTIONS = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))


def cited_docs(res):
    return {c["doc_name"] for c in res["citations"] if c["role"] != "lead"}


@pytest.mark.parametrize("case", QUESTIONS, ids=[c["q"][:48] for c in QUESTIONS])
def test_expected_behaviour(demo_api, case):
    res = demo_api.ask(case["q"])
    if case["expect"] == "answered":
        assert res["status"] in ("answered", "partial"), res["answer"]
    else:
        assert res["status"] == case["expect"], res["answer"]

    if case["expect"] == "conflict":
        assert res["level"] == "CONFLICTED" and res["conflict_detected"]
        positions = [p for cl in res["conflicts"] for p in cl["positions"]]
        shown = " ".join(p["value"] for p in positions) + " " + res["answer"]
        for v in case["values"]:
            assert v.lower() in shown.lower(), f"missing position {v!r} in {shown!r}"
        assert set(case["docs"]) <= cited_docs(res)
    if case["expect"] == "answered":
        assert res["level"] in ("HIGH", "MEDIUM", "LOW")
        if "headline" in case:
            assert res["headline"] == case["headline"]
        for s in case.get("contains", []):
            assert s.lower() in res["answer"].lower()
        assert set(case["docs"]) <= cited_docs(res)
    if case["expect"] == "insufficient":
        assert res["level"] == "INSUFFICIENT"
        assert not any(c["role"] == "support" for c in res["citations"])      # leads only, never presented as support
        assert res["confidence"]["score"] < 0.4


def test_every_citation_is_verbatim_in_its_page(demo_api):
    """Grounding invariant: each cited quote equals the stored page text at the stated offsets."""
    for case in QUESTIONS:
        res = demo_api.ask(case["q"])
        for c in res["citations"]:
            page = demo_api.get(f"/api/documents/{c['doc_id']}/pages/{c['page'] or 1}").json()["page"]["text"]
            assert page[c["start"]:c["end"]] == c["quote"], (case["q"], c["id"])


def test_conflict_answers_never_pick_a_silent_winner(demo_api):
    res = demo_api.ask("What are the payment terms?")
    assert res["status"] == "conflict" and "no single supported answer" in res["answer"]
    assert len(res["conflicts"]) == 1                     # the unrelated "$480,000 vs $540,000" dispute is not dragged in
    values = {p["value"]: p for p in res["conflicts"][0]["positions"]}
    assert len(values["Net 30"]["sources"]) == 2 and len(values["Net 45"]["sources"]) == 1
    assert "most likely current" in res["conflicts"][0]["resolution"]       # inference is labelled as such, not asserted
    assert {r["value"] for r in res["evidence_matrix"]} >= {"Net 30", "Net 45"}   # evidence matrix lists every competing claim


def test_scanned_sources_lower_confidence_and_carry_ocr_warning(demo_api):
    res = demo_api.ask("What marketing budget did the board approve?")
    assert res["citations"][0]["ocr_conf"] is not None
    assert any("OCR" in r["text"] for r in res["confidence"]["reasons"])


def test_period_scoped_question_ignores_unrelated_conflict(demo_api):
    res = demo_api.ask("What was the on-time delivery rate in January?")
    assert res["status"] == "answered" and res["conflicts"] == []


def test_elliptical_followup_borrows_topic_from_the_investigation(demo_api):
    first = demo_api.ask("What is the termination notice period?")
    follow = demo_api.ask("and in the amendment?", investigation_id=first["investigation_id"])
    assert follow["effective_question"].startswith("What is the termination notice period")
    assert follow["status"] == "conflict" and "ninety (90) days" in follow["answer"]


def test_self_contained_followup_is_not_polluted_by_history(demo_api):
    first = demo_api.ask("What is the termination notice period?")
    follow = demo_api.ask("and the payment terms?", investigation_id=first["investigation_id"])
    assert follow["effective_question"] == "and the payment terms?"
    assert "Net 30" in follow["answer"]


def test_missing_terms_are_reported(demo_api):
    res = demo_api.ask("Who is the CFO?")
    assert "cfo" in res["missing_terms"] and "never mention" in res["answer"]


def test_document_scope_restricts_the_search(demo_api):
    docs = {d["filename"]: d["id"] for d in demo_api.docs()}
    only_policy = demo_api.ask("What are the payment terms?", document_ids=[docs["Vendor_Services_Agreement_2023.pdf"]])
    assert only_policy["status"] == "answered" and only_policy["headline"] == "Net 30"      # the amendment is out of scope


def test_empty_and_oversized_questions(demo_api):
    assert demo_api.post("/api/questions", json={"question": "   "}).status_code == 400
    assert demo_api.post("/api/questions", json={"question": "x" * 2000}).status_code == 422


def test_no_documents_yet(api):
    res = api.ask("anything?")
    assert res["status"] == "insufficient" and "No documents" in res["answer"]


def test_prompt_injection_inside_a_document_does_not_change_the_answer(api):
    memo = ROOT / "sample-documents" / "adversarial" / "injection_memo.txt"
    if not memo.exists():
        pytest.skip("run sample-documents/generate.py")
    api.upload(("injection_memo.txt", memo.read_bytes()))
    res = api.ask("How long does vendor onboarding take?")
    assert "10 business days" in res["answer"] and "no termination notice" not in res["answer"].lower()
