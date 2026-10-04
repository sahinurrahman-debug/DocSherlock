"""Time-travel: the same documents, answered as of different dates."""
import pytest

from app.services.timeline import parse_day, snapshot_topic


def snap(api, day):
    r = api.get("/api/timeline", params={"as_of": day})
    assert r.status_code == 200, r.text
    return r.json()["as_of"]


def topic(snapshot, text):
    return next(t for t in snapshot["topics"] if text in t["title"] or text in t["label"])


def test_timeline_orders_documents_and_reports_range_and_undated(demo_api):
    tl = demo_api.get("/api/timeline").json()
    keys = [d["key"] for d in tl["documents"] if d["dated"]]
    assert keys == sorted(keys) and tl["range"] == {"min": "2022-08-01", "max": "2024-06-12"}
    assert tl["undated"] == ["Company_FAQ.html"] and tl["documents"][-1]["name"] == "Company_FAQ.html"
    amend = next(d for d in tl["documents"] if d["name"].startswith("Contract_Amendment"))
    assert len(amend["introduces"]) >= 3, "the amendment introduces new values for several contract terms"
    pay = next(t for t in tl["topics"] if "payable" in t["title"].lower())
    assert [h["value"] for h in pay["history"]] == ["Net 30", "Net 45", "Net 30"]            # contract, amendment, e-mail - in date order


def test_before_the_amendment_the_contract_term_is_settled_and_the_change_is_upcoming(demo_api):
    t = topic(snap(demo_api, "2023-12-31"), "payable")
    assert t["status"] == "settled" and t["value"] == "Net 30"
    assert t["source"]["doc_name"] == "Vendor_Services_Agreement_2023.pdf" and t["source"]["doc_date"] == "2023-03-03"
    assert [(u["value"], u["date"]) for u in t["upcoming"]] == [("Net 45", "2024-01-15")]


def test_on_the_amendment_date_the_new_value_is_likely_in_force(demo_api):
    t = topic(snap(demo_api, "2024-01-15"), "payable")
    assert t["status"] == "likely" and t["value"] == "Net 45" and t["basis"] == "amendment wording"
    assert t["source"]["doc_name"].startswith("Contract_Amendment") and t["alternatives"] == ["Net 30"]
    assert t["note"] == "" and t["upcoming"] == []


def test_a_later_informal_source_is_noted_but_does_not_override_a_formal_amendment(demo_api):
    t = topic(snap(demo_api, "2024-02-02"), "payable")
    assert t["value"] == "Net 45" and "Finance_Email_Acme_Payment.eml" in t["note"] and "informal" in t["note"]


def test_before_any_document_nothing_is_known(demo_api):
    s = snap(demo_api, "2020-01-01")
    assert s["documents_used"] == 0 and all(t["status"] == "not_yet" for t in s["topics"])
    assert all(t["upcoming"] for t in s["topics"]), "every point is still to come"


def test_partial_dates_count_from_the_start_of_their_period_and_undated_files_are_left_out(demo_api):
    feb, mar = snap(demo_api, "2024-02-28"), snap(demo_api, "2024-03-01")
    names = lambda s: {e["name"] for e in s["excluded"] if e["reason"] == "later"}      # noqa: E731
    assert "Annual_Report_2023_scanned.pdf" in names(feb) and "Annual_Report_2023_scanned.pdf" not in names(mar)       # dated '2024-03'
    assert any(e["reason"] == "undated" and e["name"] == "Company_FAQ.html" for e in feb["excluded"])


def test_bad_dates_are_rejected(demo_api):
    assert demo_api.get("/api/timeline", params={"as_of": "last tuesday"}).status_code == 400
    assert demo_api.get("/api/timeline", params={"as_of": "2024-02-31"}).status_code == 400
    with pytest.raises(ValueError):
        parse_day("2024-1-5")
    assert demo_api.post("/api/questions", json={"question": "x?", "as_of": "tomorrow"}).status_code == 422


def test_questions_can_be_answered_as_of_a_date(demo_api):
    before = demo_api.ask("What are the payment terms?", as_of="2023-12-31")
    assert before["status"] == "answered" and "Net 30" in before["answer"] + before["headline"] and "Net 45" not in before["answer"]
    assert before["as_of"]["date"] == "2023-12-31" and before["as_of"]["documents_used"] < before["as_of"]["documents_total"]
    assert before["caveats"][0].startswith("Answered as of 2023-12-31") and "Contract_Amendment_No1_2024-01-15.docx" in before["caveats"][0]
    assert {c["doc_name"] for c in before["citations"] if c["role"] != "lead"} == {"Vendor_Services_Agreement_2023.pdf"}

    after = demo_api.ask("What are the payment terms?", as_of="2024-06-30")
    assert after["status"] == "conflict" and {"Net 30", "Net 45"} <= {p["value"] for cl in after["conflicts"] for p in cl["positions"]}

    nothing = demo_api.ask("What are the payment terms?", as_of="2020-01-01")
    assert nothing["status"] == "insufficient" and "2020-01-01" in nothing["answer"] and nothing["as_of"]["documents_used"] == 0


def test_as_of_respects_an_explicit_document_scope(demo_api):
    ids = [d["id"] for d in demo_api.docs() if d["filename"].startswith(("Vendor", "Contract_Amendment", "Finance"))]
    res = demo_api.ask("What are the payment terms?", as_of="2024-01-20", document_ids=ids)
    assert res["as_of"]["documents_total"] == 3 and res["as_of"]["documents_used"] == 2        # the e-mail (2024-02-02) is later


def test_snapshot_logic_on_a_synthetic_cluster():
    def src(doc, date, sentence="x"):
        return {"doc_id": doc, "doc_name": f"{doc}.docx", "doc_date": date, "sentence": sentence, "start": 0, "end": 1, "page": 1, "section": "", "ocr_conf": None, "value": ""}
    cluster = {"id": "c1", "kind": "value", "severity": "high", "topic": ["fee"], "same_document": False, "time_scoped": False, "resolution": "",
               "positions": [{"value": "$10", "sources": [src("a", "2022-01-01", "The fee is $10.")]},
                             {"value": "$12", "sources": [src("b", "2023-01-01", "The fee is $12.")]}]}
    assert snapshot_topic(cluster, "2022-06-01")["status"] == "settled"
    s = snapshot_topic(cluster, "2023-06-01")                    # two known values, the newer one wins on recency alone (weaker basis)
    assert s["status"] == "likely" and s["value"] == "$12" and s["basis"] == "most recent source"
    undated = {**cluster, "positions": [{"value": "$10", "sources": [src("a", None)]}, {"value": "$12", "sources": [src("b", None)]}]}
    assert snapshot_topic(undated, "2023-06-01")["status"] == "not_yet"
