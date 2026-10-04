"""The Case Board graph is a re-shaping of the conflict clusters, so it must agree with them."""


def test_board_matches_the_conflict_clusters(demo_api):
    board = demo_api.get("/api/board").json()
    clusters = demo_api.conflicts()
    assert board["stats"]["documents"] == 11 and len(board["disputes"]) == len(clusters) == 10
    assert [d["id"] for d in board["disputes"]] == [c["id"] for c in clusters]
    for d, c in zip(board["disputes"], clusters):
        assert [p["value"] for p in d["positions"]] == [p["value"] for p in c["positions"]]
        assert d["severity"] == c["severity"]


def test_payment_dispute_shows_both_positions_with_the_amendment_as_likely_current(demo_api):
    board = demo_api.get("/api/board").json()
    d = next(x for x in board["disputes"] if {p["value"] for p in x["positions"]} == {"Net 30", "Net 45"})
    by = {p["value"]: p for p in d["positions"]}
    assert by["Net 45"]["current"] and d["basis"] == "amendment" and not by["Net 30"]["current"]
    assert {s["doc_name"] for s in by["Net 30"]["sources"]} == {"Vendor_Services_Agreement_2023.pdf", "Finance_Email_Acme_Payment.eml"}
    assert by["Net 30"]["corroborated"] and not by["Net 45"]["corroborated"], "Net 30 is stated by two different documents"
    assert d["title"].startswith("Invoices are payable ___")


def test_amendment_edges_and_unconnected_documents(demo_api):
    board = demo_api.get("/api/board").json()
    names = {d["id"]: d["name"] for d in board["documents"]}
    edges = {(names[a["newer_doc_id"]], names[a["older_doc_id"]]): a for a in board["amends"]}
    amend = edges[("Contract_Amendment_No1_2024-01-15.docx", "Vendor_Services_Agreement_2023.pdf")]
    assert amend["kind"] == "superseded" and amend["points"] >= 3
    assert edges[("Employee_Handbook_2024.docx", "IT_Security_Policy_2022.pdf")]["kind"] == "stale"
    quiet = {d["name"] for d in board["documents"] if d["disputes"] == 0}
    assert {"Company_FAQ.html", "Shipment_Performance_Q1_2024.csv"} <= quiet            # documents that agree with everything stay on the board, unconnected


def test_every_source_on_the_board_points_at_a_document_on_the_board(demo_api):
    board = demo_api.get("/api/board").json()
    ids = {d["id"] for d in board["documents"]}
    for d in board["disputes"]:
        for p in d["positions"]:
            assert p["sources"] and all(s["doc_id"] in ids for s in p["sources"])


def test_board_for_an_empty_or_agreeing_workspace(api):
    assert api.get("/api/board").json()["disputes"] == []
    api.add_text("a.txt", "# Leave\nEmployees receive twenty (20) days of paid annual leave per year.\nDate: 2024-02-01")
    board = api.get("/api/board").json()
    assert board["stats"]["documents"] == 1 and board["disputes"] == [] and board["amends"] == []
