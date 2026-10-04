def test_health(client):
    h = client.get("/health").json()
    assert h["service"] == "docsherlock" and h["database"]["ok"] and h["vector_store"]["ok"]
    assert h["llm"]["available"] is False and h["llm"]["fallback"] == "rule-based engine"


def test_upload_ask_roundtrip(api):
    doc = api.add_text("policy.txt", "# Passwords\nPasswords must be rotated every 90 days.")
    assert doc["status"] == "READY" and doc["progress"] == 100
    res = api.ask("How often must passwords be rotated?")
    assert res["status"] == "answered" and res["headline"] == "90 days" and res["level"] in ("HIGH", "MEDIUM")
    assert res["engine"]["name"] == "rules"
