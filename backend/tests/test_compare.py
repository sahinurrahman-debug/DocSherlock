"""Document comparison / temporal reasoning: what changed between two versions."""

from test_llm import FakeGroq, llm_mod, LLMClient  # reuse the fake Groq client

import pytest

OLD = ("Policy_2022.txt", "Dated: January 5, 2022\n# Coverage Limits\nThe maximum claim limit is $500,000 per policy year.\n"
       "The waiting period is 30 days before a claim can be filed.\n# Premium\nThe annual premium is $1,200 for a standard plan.\n"
       "# Retention\nClaim records are kept for 5 years.")
NEW = ("Policy_2024.txt", "Dated: March 12, 2024\n# Coverage Limits\nThe maximum claim limit is $1,000,000 per policy year.\n"
       "The waiting period is 14 days before a claim can be filed.\n# Premium\nThe annual premium is $1,200 for a standard plan.\n"
       "# Deductible\nThe deductible is $250 for every approved claim.")


@pytest.fixture()
def pair(api):
    old = api.add_text(*OLD)["id"]
    new = api.add_text(*NEW)["id"]
    return api, old, new


def test_changes_have_direction_and_size(pair):
    api, old, new = pair
    r = api.post("/api/compare", json={"document_a": old, "document_b": new}).json()
    assert r["ordered_by_date"] and r["old"]["name"] == "Policy_2022.txt" and r["new"]["name"] == "Policy_2024.txt"
    by_topic = {c["kind"]: c for c in r["changes"]}
    money = by_topic["money"]
    assert money["old"]["value"] == "$500,000" and money["new"]["value"] == "$1,000,000"
    assert money["direction"] == "increased" and money["delta"] == 500000 and "+100.0%" in money["description"]
    dur = by_topic["duration"]
    assert dur["direction"] == "decreased" and dur["delta"] == -16 and "16 days" in dur["description"]
    for c in r["changes"]:                                                   # every change points at its exact source sentences
        assert c["old"]["source"]["doc_name"] == "Policy_2022.txt" and c["new"]["source"]["doc_name"] == "Policy_2024.txt"


def test_unchanged_and_only_in_sections(pair):
    api, old, new = pair
    r = api.post("/api/compare", json={"document_a": old, "document_b": new}).json()
    assert any("$1,200" in u["value"] for u in r["unchanged"])
    assert any("$250" in x["value"] for x in r["only_in_new"]) and any("5 years" in x["value"] for x in r["only_in_old"])


def test_direction_follows_document_dates_not_selection_order(pair):
    api, old, new = pair
    r = api.post("/api/compare", json={"document_a": new, "document_b": old}).json()      # selected newest-first
    assert r["swapped"] is True and r["old"]["name"] == "Policy_2022.txt"
    assert {c["direction"] for c in r["changes"]} >= {"increased", "decreased"}


def test_undated_documents_say_the_direction_is_a_guess(api):
    a = api.add_text("A.txt", "# Limits\nThe maximum claim limit is $500,000 per policy year.")["id"]
    b = api.add_text("B.txt", "# Limits\nThe maximum claim limit is $700,000 per policy year.")["id"]
    r = api.post("/api/compare", json={"document_a": a, "document_b": b}).json()
    assert r["ordered_by_date"] is False and any("no date" in c for c in r["caveats"])
    assert r["changes"][0]["direction"] == "increased"


def test_compare_validation(pair):
    api, old, new = pair
    assert api.post("/api/compare", json={"document_a": old, "document_b": old}).status_code == 400
    assert api.post("/api/compare", json={"document_a": old, "document_b": "missing"}).status_code == 404


def test_comparison_question_is_routed_to_the_comparison_engine(pair):
    api, old, new = pair
    res = api.ask("What changed between the 2022 and 2024 policies?")
    assert res["status"] == "answered" and res["level"] == "HIGH" and res["comparison"]["changes"]
    assert "→" in res["answer"] and "$1,000,000" in res["answer"]
    assert {c["doc_name"] for c in res["citations"]} == {"Policy_2022.txt", "Policy_2024.txt"}
    assert res["trace"]["intent"] == "compare"


def test_vague_comparison_question_falls_back_to_normal_search(pair):
    api, *_ = pair
    res = api.ask("Compare everything please")
    assert res["trace"].get("intent") != "compare"


def test_llm_summary_is_used_only_if_it_adds_no_new_numbers(pair, ):
    api, old, new = pair
    good = "The claim limit doubled from $500,000 to $1,000,000 and the waiting period fell from 30 days to 14 days."
    llm_mod.set_llm(LLMClient(client=FakeGroq(lambda s, u, kw: {"summary": good})))
    try:
        r = api.post("/api/compare", json={"document_a": old, "document_b": new}).json()
        # settings.llm_available is False without a key, so the HTTP endpoint stays rule-based ...
        assert r["engine"] == "rules"
        from app.services import comparison
        from app.services.corpus import corpus_cache
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            corpus = corpus_cache.get(db, api.session, [old, new])
            result = comparison.compare(corpus, old, new)
        finally:
            db.close()
        # ... while the guarded summary helper itself accepts a faithful summary and rejects an invented number
        assert comparison.llm_summary(result, LLMClient(client=FakeGroq(lambda s, u, kw: {"summary": good}))) == good
        bad = good + " Premiums rose to $1,900."
        assert comparison.llm_summary(result, LLMClient(client=FakeGroq(lambda s, u, kw: {"summary": bad}))) is None
        assert comparison.llm_summary(result, LLMClient(client=FakeGroq(lambda s, u, kw: RuntimeError("x")))) is None
    finally:
        llm_mod.set_llm(None)
