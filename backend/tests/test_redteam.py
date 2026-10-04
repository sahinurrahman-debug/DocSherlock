"""Red-Team mode: honest answers survive, and tampered or careless answers are caught."""
import copy

from app.core.database import SessionLocal
from app.models.investigation import Question
from app.services import redteam
from app.services.llm import LLMClient
from test_llm import FakeGroq, find, passages  # noqa: F401  (reuse the fake Groq client)


def checks(result):
    return {c["id"]: c for c in result["checks"]}


def challenge(api, qid, **body):
    r = api.post(f"/api/questions/{qid}/challenge", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def payload_of(qid):
    with SessionLocal() as db:
        return copy.deepcopy(db.get(Question, qid).payload), db.get(Question, qid).session_id


def test_a_well_grounded_answer_survives(demo_api):
    res = demo_api.ask("What is the late payment interest rate?")
    out = challenge(demo_api, res["id"], use_llm=False)
    c = checks(out)
    assert out["verdict"] == "survived" and out["adversary"] == "rules"
    assert c["quotes"]["status"] == "passed" and c["values"]["status"] == "passed" and c["contradictions"]["status"] == "passed"
    assert out["headline"].startswith("Survived")


def test_a_conflict_answer_that_shows_every_position_is_not_accused_of_hiding_one(demo_api):
    res = demo_api.ask("What are the payment terms?")
    assert res["status"] == "conflict"
    out = challenge(demo_api, res["id"], use_llm=False)
    c = checks(out)
    assert c["contradictions"]["status"] == "passed" and "shows all positions" in c["contradictions"]["detail"]
    assert out["verdict"] in ("survived", "weakened") and c["single_source"]["status"] == "skipped"


def test_the_verdict_is_stored_with_the_answer(demo_api):
    res = demo_api.ask("What is the liability cap?")
    out = challenge(demo_api, res["id"], use_llm=False)
    stored = demo_api.get(f"/api/questions/{res['id']}").json()
    assert stored["redteam"]["verdict"] == out["verdict"] and stored["redteam"]["ran_at"] == out["ran_at"]


def test_an_invented_figure_is_refuted(demo_api):
    res = demo_api.ask("What is the late payment interest rate?")
    payload, sid = payload_of(res["id"])
    payload["answer"] += " The cap is $9,999,999."
    with SessionLocal() as db:
        out = redteam.challenge(db, sid, payload, None, use_llm=False)
    v = checks(out)["values"]
    assert out["verdict"] == "refuted" and v["status"] == "failed" and v["severity"] == "critical" and "9999999" in v["detail"].replace(",", "")


def test_a_doctored_quote_is_refuted(demo_api):
    res = demo_api.ask("What is the liability cap?")
    payload, sid = payload_of(res["id"])
    payload["citations"][0]["quote"] = payload["citations"][0]["quote"].replace("cap", "limit", 1) or "tampered"
    payload["citations"][0]["quote"] += " (tampered)"
    with SessionLocal() as db:
        out = redteam.challenge(db, sid, payload, None, use_llm=False)
    q = checks(out)["quotes"]
    assert q["status"] == "failed" and q["severity"] == "critical" and out["verdict"] == "refuted"


def test_ignoring_a_dispute_the_cited_passage_is_part_of_is_caught_and_names_the_newer_source(demo_api):
    res = demo_api.ask("What are the payment terms?")
    payload, sid = payload_of(res["id"])
    payload["conflicts"] = []                                   # pretend the answer swallowed the conflict and picked one side
    payload["status"] = "answered"
    with SessionLocal() as db:
        out = redteam.challenge(db, sid, payload, None, use_llm=False)
    c = checks(out)["contradictions"]
    assert c["status"] == "failed" and c["severity"] == "critical" and out["verdict"] == "refuted"
    assert "Contract_Amendment_No1_2024-01-15.docx" in c["detail"] and "more current" in c["detail"]
    assert {e["doc_name"] for e in c["evidence"]} >= {"Vendor_Services_Agreement_2023.pdf", "Contract_Amendment_No1_2024-01-15.docx"}


def test_a_refusal_has_nothing_to_attack(demo_api):
    res = demo_api.ask("What is the share price of Northwind?")
    out = challenge(demo_api, res["id"], use_llm=False)
    assert res["status"] == "insufficient" and out["verdict"] == "survived" and checks(out)["refusal"]["status"] == "passed"


def test_single_source_and_exception_wording_are_flagged_as_minor_notes(api):
    api.add_text("policy.txt", "# Leave\nEmployees receive twenty (20) days of paid annual leave per year.\nThis does not apply to contractors, unless a written agreement says otherwise.\nDate: 2024-02-01")
    res = api.ask("How many days of paid annual leave do employees receive?")
    out = challenge(api, res["id"], use_llm=False)
    c = checks(out)
    assert c["single_source"]["status"] == "failed" and c["single_source"]["severity"] == "minor"
    assert out["verdict"] == "survived" and out["concerns"] >= 1                 # minor notes never downgrade the verdict
    assert "survived" in out["headline"].lower() and "minor note" in out["headline"]


def test_the_llm_adversary_counts_only_objections_with_verbatim_quotes(demo_api):
    res = demo_api.ask("What is the late payment interest rate?")
    payload, sid = payload_of(res["id"])
    real = payload["citations"][0]["quote"]

    def adversary(responder_quote):
        def responder(system, user, kw):
            assert "adversarial reviewer" in system and "<passage id=" in user
            pid = next(iter(passages(user)))
            return {"verdict": "wrong", "attacks": [{"objection": "The interest rate is expressed per year, not per month.", "passage_id": pid, "quote": responder_quote}]}
        return LLMClient(client=FakeGroq(responder))

    with SessionLocal() as db:
        fabricated = redteam.challenge(db, sid, payload, adversary("this sentence appears nowhere in the documents"), use_llm=True)
        genuine = redteam.challenge(db, sid, payload, adversary(real), use_llm=True)
    assert checks(fabricated)["adversary"]["status"] == "passed" and "not verbatim" in checks(fabricated)["adversary"]["detail"]
    adv = checks(genuine)["adversary"]
    assert adv["status"] == "failed" and adv["severity"] == "major" and adv["evidence"][0]["quote"] == real and genuine["verdict"] == "weakened"
    assert genuine["adversary"] == "llm"


def test_an_unavailable_llm_skips_only_the_adversary(demo_api):
    res = demo_api.ask("What is the liability cap?")
    payload, sid = payload_of(res["id"])
    from app.services.llm import LLMUnavailable

    class Broken(LLMClient):
        def complete_json(self, *a, **k):
            raise LLMUnavailable("down")
    with SessionLocal() as db:
        out = redteam.challenge(db, sid, payload, Broken(client=object()), use_llm=True)
    assert checks(out)["adversary"]["status"] == "skipped" and out["verdict"] == "survived" and out["adversary"] == "rules"


def test_cannot_challenge_someone_elses_answer(client, demo_api):
    from conftest import Api
    res = demo_api.ask("What is the liability cap?")
    stranger = Api(client, "red-team-stranger-01")
    assert stranger.post(f"/api/questions/{res['id']}/challenge", json={}).status_code == 404
