"""Conflict detection: true positives AND the false-positive guards that make the feature trustworthy."""
from conftest import add_text


def conflicts_between(engine, a_text, b_text, a_name="Doc_A.txt", b_name="Doc_B.txt"):
    add_text(engine, a_name, a_text)
    add_text(engine, b_name, b_text)
    return engine.conflicts()


def test_detects_value_conflict_across_documents(engine):
    cs = conflicts_between(engine, "# Payment Terms\nInvoices are payable Net 30 from the invoice date.",
                           "# Payment Terms\nInvoices are payable Net 45 from the invoice date.")
    assert len(cs) == 1
    assert {p["value"] for p in cs[0]["positions"]} == {"Net 30", "Net 45"}


def test_same_value_different_wording_is_not_a_conflict(engine):
    assert conflicts_between(engine, "Notice of sixty (60) days is required to terminate the agreement.",
                             "Either party may terminate the agreement with 2 months written notice.") == []


def test_unit_conversion_months_vs_days_conflicts_only_when_different(engine):
    cs = conflicts_between(engine, "Notice of 60 days is required to terminate the agreement.",
                           "Notice of 3 months is required to terminate the agreement.")
    assert len(cs) == 1                     # 60 days vs 90 days


def test_different_periods_are_not_conflicts(engine):
    assert conflicts_between(engine, "Q1 revenue was $5 million for Northwind.", "Q2 revenue was $7 million for Northwind.") == []
    assert conflicts_between(engine, "In 2022 revenue was $5 million.", "In 2023 revenue was $7 million.", "r1.txt", "r2.txt") == []


def test_different_entities_are_not_conflicts(engine):
    assert conflicts_between(engine, "Alice's annual salary is $90,000.", "Bob's annual salary is $95,000.") == []


def test_as_of_dates_scope_a_statement(engine):
    assert conflicts_between(engine, "As of December 31, 2023 the company employed 142 employees.",
                             "As of June 30, 2024 the company employed 128 employees.") == []


def test_event_dates_conflict(engine):
    cs = conflicts_between(engine, "The agreement was signed on March 3, 2023 by both parties.",
                           "The agreement was signed on March 5, 2023 by both parties.")
    assert len(cs) == 1 and cs[0]["value_kind"] == "date"


def test_unrelated_subjects_with_same_unit_are_not_conflicts(engine):
    assert conflicts_between(engine, "Termination requires 60 days written notice.", "Invoices are payable within 30 days of receipt.") == []


def test_table_rows_in_one_document_do_not_conflict(engine):
    add_text(engine, "rates.csv", "Month,Rate (%)\nJanuary,96.2\nFebruary,94.8\nMarch,95.9\n")
    assert engine.conflicts() == []


def test_same_document_inconsistency_is_flagged_as_such(engine):
    add_text(engine, "Policy.txt", "Passwords must be rotated every 90 days.\n\nElsewhere. Passwords must be rotated every 60 days.")
    cs = engine.conflicts()
    assert len(cs) == 1 and cs[0]["same_document"] is True
    assert "internal inconsistency" in cs[0]["resolution"]


def test_assertion_conflict_antonyms(engine):
    cs = conflicts_between(engine, "Multi-factor authentication is mandatory for all remote access to company systems.",
                           "Multi-factor authentication is optional for remote access to company systems.")
    assert len(cs) == 1 and cs[0]["kind"] == "assertion"


def test_three_way_disagreement_is_one_cluster_with_grouped_positions(engine):
    add_text(engine, "Contract_2023-01-01.txt", "Dated: January 1, 2023\n# Payment Terms\nInvoices are payable Net 30 from the invoice date.")
    add_text(engine, "Amendment_2024-01-01.txt", "Dated: January 1, 2024\n# Payment Terms\nSection 3 is amended so that invoices are payable Net 45 from the invoice date.")
    add_text(engine, "Email_thread.txt", "Dated: March 1, 2024\n# Payment Terms\nPer the contract invoices are payable Net 30 from the invoice date.")
    cs = engine.conflicts()
    assert len(cs) == 1
    by_value = {p["value"]: p for p in cs[0]["positions"]}
    assert set(by_value) == {"Net 30", "Net 45"}
    assert len(by_value["Net 30"]["sources"]) == 2
    # the amendment (formal, amendment wording, newer than the contract) is the likely current position,
    # and the later informal email is noted rather than allowed to win
    assert "most likely current" in cs[0]["resolution"] and "Amendment_2024-01-01.txt" in cs[0]["resolution"]
    assert "Email_thread.txt" in cs[0]["resolution"]


def test_doc_date_edit_changes_resolution_reasoning(engine):
    a = add_text(engine, "Report_A.txt", "Total headcount: the company has 142 employees today.")["id"]
    b = add_text(engine, "Report_B.txt", "Total headcount: the company has 128 employees today.")["id"]
    before = engine.conflicts()[0]["resolution"]
    assert "can't tell" in before
    engine.set_doc_date(a, "2023-01-01")
    engine.set_doc_date(b, "2024-06-01")
    after = engine.conflicts()[0]["resolution"]
    assert "Report_B.txt" in after and "most recent" in after


def test_deleting_a_document_removes_its_conflicts(engine):
    a = add_text(engine, "A.txt", "Invoices are payable Net 30 from the invoice date.")["id"]
    add_text(engine, "B.txt", "Invoices are payable Net 45 from the invoice date.")
    assert len(engine.conflicts()) == 1
    engine.delete(a)
    assert engine.conflicts() == []
