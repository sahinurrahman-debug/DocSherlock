"""The Case File: findings produced from the document set alone, before any question is asked."""
from conftest import Api


def finding(cf, **match):
    return [f for f in cf["findings"] if all(f.get(k) == v for k, v in match.items())]


def test_demo_set_produces_a_case_file_without_any_question(demo_api):
    cf = demo_api.get("/api/casefile").json()
    assert cf["stats"]["documents"] == 11 and cf["stats"]["disputed_points"] == 10
    assert "10 points are disputed" in cf["briefing"] and "11 documents" in cf["briefing"]
    types = {f["type"] for f in cf["findings"]}
    assert {"conflict", "superseded", "stale", "undated"} <= types
    sev = [f["severity"] for f in cf["findings"]]
    assert sev == sorted(sev, key=["high", "medium", "low"].index), "findings are ordered most severe first"


def test_payment_dispute_names_both_values_and_the_likely_current_one(demo_api):
    cf = demo_api.get("/api/casefile").json()
    f = next(x for x in cf["findings"] if x["type"] == "conflict" and "Net 30" in x["title"] and "Net 45" in x["title"])
    assert f["severity"] == "high" and f["basis"] == "amendment" and f["likely_current"] is not None
    assert "Net 45" in f["detail"] and "No document explicitly states" in f["detail"]        # inference is labelled as such
    assert {e["doc_name"] for e in f["evidence"]} >= {"Vendor_Services_Agreement_2023.pdf", "Contract_Amendment_No1_2024-01-15.docx"}
    assert f["question"] and "?" in f["question"]


def test_amendment_is_reported_as_superseding_and_a_plain_newer_document_as_possibly_stale(demo_api):
    cf = demo_api.get("/api/casefile").json()
    sup = finding(cf, type="superseded")
    assert len(sup) == 1 and "Vendor_Services_Agreement_2023.pdf" in sup[0]["title"] and "Contract_Amendment_No1" in sup[0]["title"]
    assert sup[0]["points"] >= 3
    stale = {f["title"] for f in finding(cf, type="stale")}
    assert any("IT_Security_Policy_2022.pdf" in t for t in stale)
    docs = {d["name"]: d for d in cf["documents"]}
    assert docs["IT_Security_Policy_2022.pdf"]["overridden_by"] == ["Employee_Handbook_2024.docx"]
    assert docs["Company_FAQ.html"]["disputed_points"] == 0


def test_every_evidence_quote_is_verbatim_at_its_offsets(demo_api):
    cf = demo_api.get("/api/casefile").json()
    pages = {}
    checked = 0
    for f in cf["findings"]:
        for e in f["evidence"]:
            key = (e["doc_id"], e["page"] or 1)
            if key not in pages:
                pages[key] = demo_api.get(f"/api/documents/{e['doc_id']}/pages/{key[1]}").json()["page"]["text"]
            assert pages[key][e["start"]:e["end"]] == e["quote"], (f["title"], e["doc_name"])
            checked += 1
    assert checked >= 10


def test_undated_documents_are_flagged_with_advice(demo_api):
    f = finding(demo_api.get("/api/casefile").json(), type="undated")[0]
    assert "Company_FAQ.html" in f["detail"] and f["severity"] == "low" and "date chip" in f["detail"]


def test_clean_set_and_empty_workspace_are_handled(api):
    empty = api.get("/api/casefile").json()
    assert empty["findings"] == [] and empty["stats"]["documents"] == 0 and "0 documents" in empty["briefing"]

    api.add_text("policy_a.txt", "# Leave\nEmployees receive twenty (20) days of paid annual leave per calendar year.\nDate: 2024-02-01")
    api.add_text("policy_b.txt", "# Leave\nStaff are entitled to 20 days of paid annual leave each year.\nDate: 2024-03-01")
    cf = api.get("/api/casefile").json()
    assert cf["stats"]["disputed_points"] == 0 and not finding(cf, type="conflict")
    assert "No contradictions were found" in cf["briefing"]


def test_scope_and_isolation(client, demo_api):
    other = Api(client, "casefile-other-session")
    assert other.get("/api/casefile").json()["stats"]["documents"] == 0                      # another visitor sees nothing of ours
    ids = [d["id"] for d in demo_api.docs() if d["filename"].startswith(("Vendor", "Contract_Amendment"))]
    cf = demo_api.get("/api/casefile", params={"document_ids": ",".join(ids)}).json()
    assert cf["stats"]["documents"] == 2 and all(f["type"] != "stale" or "IT_Security" not in f["title"] for f in cf["findings"])


def test_unreadable_and_low_confidence_scans_are_called_out(api):
    api.upload(("blank.txt", b"   \n  "), expect_ok=True)
    cf = api.get("/api/casefile").json()
    docs = {d["name"]: d for d in cf["documents"]}
    if "blank.txt" in docs and not docs["blank.txt"]["readable"]:
        assert finding(cf, type="unreadable")


def test_subject_phrase_is_readable_whole_words():
    from app.services.supersession import subject_phrase
    cluster = {"kind": "value", "topic": ["payment"], "positions": [{"value": "$480,000", "sources": [
        {"sentence": "The total contract value is $480,000, payable in equal monthly instalments over the term."}]}]}
    assert subject_phrase(cluster) == "The total contract value is ___, payable in equal monthly \u2026"
