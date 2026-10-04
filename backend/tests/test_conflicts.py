"""Conflict detection through the API: true positives AND the false-positive guards that make the feature trustworthy."""


def conflicts_between(api, a_text, b_text, a_name="Doc_A.txt", b_name="Doc_B.txt"):
    api.add_text(a_name, a_text)
    api.add_text(b_name, b_text)
    return api.conflicts()


def test_detects_value_conflict_across_documents(api):
    cs = conflicts_between(api, "# Payment Terms\nInvoices are payable Net 30 from the invoice date.",
                           "# Payment Terms\nInvoices are payable Net 45 from the invoice date.")
    assert len(cs) == 1
    assert {p["value"] for p in cs[0]["positions"]} == {"Net 30", "Net 45"}


def test_same_value_different_wording_is_not_a_conflict(api):
    assert conflicts_between(api, "Notice of sixty (60) days is required to terminate the agreement.",
                             "Either party may terminate the agreement with 2 months written notice.") == []


def test_unit_conversion_months_vs_days_conflicts_only_when_different(api):
    cs = conflicts_between(api, "Notice of 60 days is required to terminate the agreement.",
                           "Notice of 3 months is required to terminate the agreement.")
    assert len(cs) == 1                     # 60 days vs 90 days


def test_different_periods_are_not_conflicts(api):
    assert conflicts_between(api, "Q1 revenue was $5 million for Northwind.", "Q2 revenue was $7 million for Northwind.") == []
    assert conflicts_between(api, "In 2022 revenue was $5 million.", "In 2023 revenue was $7 million.", "r1.txt", "r2.txt") == []


def test_different_entities_are_not_conflicts(api):
    assert conflicts_between(api, "Alice's annual salary is $90,000.", "Bob's annual salary is $95,000.") == []


def test_as_of_dates_scope_a_statement(api):
    assert conflicts_between(api, "As of December 31, 2023 the company employed 142 employees.",
                             "As of June 30, 2024 the company employed 128 employees.") == []


def test_event_dates_conflict(api):
    cs = conflicts_between(api, "The agreement was signed on March 3, 2023 by both parties.",
                           "The agreement was signed on March 5, 2023 by both parties.")
    assert len(cs) == 1 and cs[0]["value_kind"] == "date"


def test_unrelated_subjects_with_same_unit_are_not_conflicts(api):
    assert conflicts_between(api, "Termination requires 60 days written notice.", "Invoices are payable within 30 days of receipt.") == []


def test_table_rows_in_one_document_do_not_conflict(api):
    api.upload(("rates.csv", b"Month,Rate (%)\nJanuary,96.2\nFebruary,94.8\nMarch,95.9\n"))
    assert api.conflicts() == []


def test_same_document_inconsistency_is_flagged_as_such(api):
    api.add_text("Policy.txt", "Passwords must be rotated every 90 days.\n\nElsewhere. Passwords must be rotated every 60 days.")
    cs = api.conflicts()
    assert len(cs) == 1 and cs[0]["same_document"] is True
    assert "internal inconsistency" in cs[0]["resolution"]


def test_assertion_conflict_antonyms(api):
    cs = conflicts_between(api, "Multi-factor authentication is mandatory for all remote access to company systems.",
                           "Multi-factor authentication is optional for remote access to company systems.")
    assert len(cs) == 1 and cs[0]["kind"] == "assertion"


def test_three_way_disagreement_is_one_cluster_with_grouped_positions(api):
    api.add_text("Contract_2023-01-01.txt", "Dated: January 1, 2023\n# Payment Terms\nInvoices are payable Net 30 from the invoice date.")
    api.add_text("Amendment_2024-01-01.txt", "Dated: January 1, 2024\n# Payment Terms\nSection 3 is amended so that invoices are payable Net 45 from the invoice date.")
    api.add_text("Email_thread.txt", "Dated: March 1, 2024\n# Payment Terms\nPer the contract invoices are payable Net 30 from the invoice date.")
    cs = api.conflicts()
    assert len(cs) == 1
    by_value = {p["value"]: p for p in cs[0]["positions"]}
    assert set(by_value) == {"Net 30", "Net 45"}
    assert len(by_value["Net 30"]["sources"]) == 2
    # the amendment (formal, amendment wording, newer than the contract) is the likely current position,
    # and the later informal email is noted rather than allowed to win
    assert "most likely current" in cs[0]["resolution"] and "Amendment_2024-01-01.txt" in cs[0]["resolution"]
    assert "Email_thread.txt" in cs[0]["resolution"]


def test_doc_date_edit_changes_resolution_reasoning(api):
    a = api.add_text("Report_A.txt", "Total headcount: the company has 142 employees today.")["id"]
    b = api.add_text("Report_B.txt", "Total headcount: the company has 128 employees today.")["id"]
    assert "can't tell" in api.conflicts()[0]["resolution"]
    assert api.patch(f"/api/documents/{a}", json={"doc_date": "2023-01-01"}).status_code == 200
    assert api.patch(f"/api/documents/{b}", json={"doc_date": "2024-06-01"}).status_code == 200
    after = api.conflicts()[0]["resolution"]
    assert "Report_B.txt" in after and "most recent" in after


def test_deleting_a_document_removes_its_conflicts(api):
    a = api.add_text("A.txt", "Invoices are payable Net 30 from the invoice date.")["id"]
    api.add_text("B.txt", "Invoices are payable Net 45 from the invoice date.")
    assert len(api.conflicts()) == 1
    assert api.delete(f"/api/documents/{a}").status_code == 204
    assert api.conflicts() == []


def test_conflicts_can_be_scoped_to_selected_documents(api):
    a = api.add_text("A.txt", "# Payment Terms\nInvoices are payable Net 30 from the invoice date.")["id"]
    b = api.add_text("B.txt", "# Payment Terms\nInvoices are payable Net 45 from the invoice date.")["id"]
    c = api.add_text("C.txt", "# Payment Terms\nInvoices are payable Net 45 from the invoice date.")["id"]
    assert len(api.conflicts(document_ids=f"{a},{b}")) == 1
    assert api.conflicts(document_ids=f"{b},{c}") == []
