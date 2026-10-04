"""Groq answer path with a fake client: grounding must hold even if the model misbehaves, and every failure must fall back."""
import json
import re
from types import SimpleNamespace

import groq
import httpx
import pytest
from conftest import ROOT

from app.core.config import settings
from app.services import llm as llm_mod
from app.services.llm import LLMClient


def _resp_headers(h=None):
    return httpx.Response(429, headers=h or {}, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))


class FakeGroq:
    """Mimics groq.Groq(): chat.completions.create(**kw). `responder(system, user, kw) -> dict | Exception`."""

    def __init__(self, responder, finish="stop"):
        self.responder, self.finish, self.calls = responder, finish, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        out = self.responder(kw["messages"][0]["content"], kw["messages"][1]["content"], kw)
        if isinstance(out, Exception):
            raise out
        text = out if isinstance(out, str) else json.dumps(out)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=self.finish, message=SimpleNamespace(content=text))],
                               usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=300))


@pytest.fixture()
def use_llm():
    def install(responder, **kw):
        fake = FakeGroq(responder, **kw)
        llm_mod.set_llm(LLMClient(client=fake))
        return fake
    yield install
    llm_mod.set_llm(None)


def passages(user):
    return {m.group(1): m.group(3) for m in re.finditer(r'<passage id="(P\d+)" ([^>]*)>\n(.*?)\n</passage>', user, re.S)}


def find(user, needle):
    for pid, text in passages(user).items():
        if needle in text:
            return pid, text
    raise AssertionError(f"{needle!r} not in prompt")


def sentence_with(text, needle):
    return next(s for s in re.split(r"(?<=[.])\s+", text) if needle in s)


def base(**kw):
    d = {"status": "answered", "headline": "", "answer": "", "confidence": "high", "claims": [], "extracted_claims": [], "conflicts": [],
         "dismissed_candidates": [], "caveats": []}
    d.update(kw)
    return d


def ask(demo_api, q, **kw):
    return demo_api.ask(q, mode=kw.pop("mode", "auto"), **kw)


# --------------------------------------------------------------------------------------------------
def test_conflict_adjudication_with_verified_quotes_and_request_shape(demo_api, use_llm):
    def respond(system, user, kw):
        p30, t30 = find(user, "Net 30 from the invoice date")
        p45, t45 = find(user, "Net 45")
        q30, q45 = sentence_with(t30, "Net 30"), sentence_with(t45, "Net 45")
        return base(status="conflict", headline="Net 30 vs Net 45", answer=f"The contract says Net 30 [{p30}] but the amendment says Net 45 [{p45}].",
                    claims=[{"text": "Net 30", "sources": [{"passage": p30, "quote": q30}]}, {"text": "Net 45", "sources": [{"passage": p45, "quote": q45}]}],
                    extracted_claims=[{"subject": "payment terms", "predicate": "are", "value": "Net 30", "date": "2023-03-03", "passage": p30, "quote": q30},
                                      {"subject": "payment terms", "predicate": "are", "value": "Net 45", "date": "2024-01-15", "passage": p45, "quote": q45}],
                    conflicts=[{"candidate_id": "C1", "summary": "Payment terms differ between contract and amendment",
                                "positions": [{"passage": p30, "claim": "Net 30", "quote": q30}, {"passage": p45, "claim": "Net 45", "quote": q45}],
                                "resolution": "The amendment is later and says it amends Section 3."}])
    fake = use_llm(respond)
    res = ask(demo_api, "What are the payment terms?")
    assert res["engine"]["name"] == "groq" and res["engine"]["model"] == settings.groq_model and not res["engine"]["fallback"]
    assert res["status"] == "conflict" and res["level"] == "CONFLICTED"
    assert {p["value"] for p in res["conflicts"][0]["positions"]} == {"Net 30", "Net 45"}
    assert all(c["verified"] for c in res["citations"])
    assert "[S1]" in res["answer"] and "[P" not in res["answer"]                       # model passage ids mapped onto verified citations
    assert {m["value"] for m in res["evidence_matrix"]} == {"Net 30", "Net 45"}         # structured claims survive verification
    assert any("verified verbatim" in r["text"] for r in res["confidence"]["reasons"])
    assert res["engine"]["tokens"]["prompt"] == 1200
    kw = fake.calls[0]                                                                   # request shape
    assert kw["model"] == "openai/gpt-oss-120b" and kw["temperature"] == 0
    assert kw["response_format"]["type"] == "json_schema" and kw["response_format"]["json_schema"]["strict"] is True
    assert kw["reasoning_effort"] == settings.groq_reasoning_effort and kw["include_reasoning"] is False
    system = kw["messages"][0]["content"]
    assert "untrusted data" in system and "Use ONLY the passages" in system
    assert "<rule_engine_conflict_candidates>" in kw["messages"][1]["content"]


def test_non_strict_models_use_json_object_with_the_schema_in_the_prompt(demo_api, use_llm, monkeypatch):
    monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "groq_fallback_model", "")
    def respond(system, user, kw):
        pid, text = find(user, "capped at $1,000,000")
        return base(headline="$1,000,000", answer=f"Capped [{pid}].", claims=[{"text": "cap", "sources": [{"passage": pid, "quote": sentence_with(text, "capped at $1,000,000")}]}])
    fake = use_llm(respond)
    res = ask(demo_api, "What is the liability cap?")
    kw = fake.calls[0]
    assert kw["response_format"] == {"type": "json_object"} and "JSON Schema" in kw["messages"][0]["content"]
    assert "reasoning_effort" not in kw
    assert res["status"] == "answered" and res["headline"] == "$1,000,000" and res["engine"]["model"] == "llama-3.3-70b-versatile"


def test_fabricated_quotes_are_discarded_and_answer_withheld(demo_api, use_llm):
    def respond(system, user, kw):
        pid, _ = find(user, "capped at $1,000,000")
        return base(answer=f"Liability is unlimited [{pid}].", headline="Unlimited",
                    claims=[{"text": "unlimited", "sources": [{"passage": pid, "quote": "Liability is unlimited for data breaches."}]}])
    use_llm(respond)
    res = ask(demo_api, "What is the liability cap?")
    assert res["status"] == "insufficient" and res["level"] == "INSUFFICIENT" and res["headline"] == ""
    assert not any(c["role"] == "support" for c in res["citations"])
    assert any("verifiable" in c or "withheld" in c for c in res["caveats"])


def test_fabricated_model_output_cannot_hide_a_verified_disagreement(demo_api, use_llm):
    def respond(system, user, kw):
        pid, _ = find(user, "Net 45")
        return base(answer=f"Payment is due Net 90 [{pid}].", headline="Net 90",
                    claims=[{"text": "Net 90", "sources": [{"passage": pid, "quote": "Invoices are payable Net 90 from the invoice date."}]}])
    use_llm(respond)
    res = ask(demo_api, "What are the payment terms?")
    assert res["status"] == "conflict" and "Net 90" not in str(res["conflicts"]) + res["headline"]
    assert {p["value"] for p in res["conflicts"][0]["positions"]} == {"Net 30", "Net 45"}


def test_partially_fabricated_support_lowers_confidence(demo_api, use_llm):
    def good(system, user, kw):
        pid, text = find(user, "capped at $1,000,000")
        return base(headline="$1,000,000", answer=f"Capped [{pid}].", claims=[{"text": "cap", "sources": [{"passage": pid, "quote": sentence_with(text, "capped at $1,000,000")}]}])

    def dirty(system, user, kw):
        d = good(system, user, kw)
        d["claims"][0]["sources"].append({"passage": d["claims"][0]["sources"][0]["passage"], "quote": "Liability is unlimited for data breaches."})
        return d
    use_llm(good)
    clean = ask(demo_api, "What is the liability cap?")
    use_llm(dirty)
    bad = ask(demo_api, "What is the liability cap?")
    assert bad["confidence"]["score"] < clean["confidence"]["score"]
    assert any("could not be verified" in r["text"] for r in bad["confidence"]["reasons"])


def test_unverifiable_conflict_claim_is_downgraded(demo_api, use_llm):
    def respond(system, user, kw):
        pid, text = find(user, "Net 45")
        return base(status="conflict", answer="Sources disagree.", confidence="medium",
                    claims=[{"text": "x", "sources": [{"passage": pid, "quote": sentence_with(text, "Net 45")}]}],
                    conflicts=[{"candidate_id": "", "summary": "made up", "resolution": "",
                                "positions": [{"passage": pid, "claim": "Net 45", "quote": sentence_with(text, "Net 45")},
                                              {"passage": pid, "claim": "Net 12", "quote": "Payment is Net 12 days after delivery."}]}])
    use_llm(respond)
    res = ask(demo_api, "What are the payment terms?")
    assert res["status"] != "conflict" or len(res["conflicts"][0]["positions"]) >= 2
    assert any("could not be verified" in c or "no verifiable pair" in c or "gave no verifiable" in c for c in res["caveats"])


def test_a_firm_disagreement_cannot_be_dismissed_by_the_model(demo_api, use_llm):
    """Real-world regression: the model called the amendment 'a replacement' and answered 'Net 45' silently."""
    def respond(system, user, kw):
        pid, text = find(user, "Net 45")
        return base(answer=f"Per the amendment, Net 45 [{pid}].", headline="Net 45", confidence="high",
                    claims=[{"text": "Net 45", "sources": [{"passage": pid, "quote": sentence_with(text, "Net 45")}]}],
                    dismissed_candidates=[{"candidate_id": "C1", "reason": "the amendment explicitly replaces the original term"}])
    use_llm(respond)
    res = ask(demo_api, "What are the payment terms?")
    assert res["status"] == "conflict" and res["level"] == "CONFLICTED"
    assert {p["value"] for p in res["conflicts"][0]["positions"]} == {"Net 30", "Net 45"}
    assert "Model's assessment" in res["conflicts"][0]["resolution"] and "explicitly replaces" in res["conflicts"][0]["resolution"]
    assert any("still reported as a conflict" in c for c in res["caveats"])
    assert all(s.get("cite") for p in res["conflicts"][0]["positions"] for s in p["sources"])        # sources are verified citations
    assert {c["role"] for c in res["citations"]} == {"conflict"}


def test_a_firm_disagreement_the_model_ignores_is_still_reported(demo_api, use_llm):
    def respond(system, user, kw):
        pid, text = find(user, "Net 45")
        return base(answer=f"Net 45 [{pid}].", headline="Net 45", confidence="high",
                    claims=[{"text": "Net 45", "sources": [{"passage": pid, "quote": sentence_with(text, "Net 45")}]}])
    use_llm(respond)
    res = ask(demo_api, "What are the payment terms?")
    assert res["status"] == "conflict" and len(res["conflicts"][0]["positions"]) == 2


def test_a_weaker_candidate_can_still_be_dismissed_with_a_reason(demo_api, use_llm):
    def respond(system, user, kw):
        pid, text = find(user, "142 employees")
        return base(answer=f"142 employees [{pid}].", headline="142 employees", confidence="medium",
                    claims=[{"text": "142", "sources": [{"passage": pid, "quote": sentence_with(text, "142 employees")}]}],
                    dismissed_candidates=[{"candidate_id": "C1", "reason": "the board minutes describe a later point in time"}])
    use_llm(respond)
    res = ask(demo_api, "How many employees does Northwind have?")
    assert res["status"] == "answered" and res["conflicts"] == []
    assert any("judged not to be real" in c for c in res["caveats"])


def test_a_weaker_candidate_the_model_ignores_caps_confidence(demo_api, use_llm):
    def respond(system, user, kw):
        pid, text = find(user, "142 employees")
        return base(answer=f"142 employees [{pid}].", headline="142 employees", confidence="high",
                    claims=[{"text": "142", "sources": [{"passage": pid, "quote": sentence_with(text, "142 employees")}]}])
    use_llm(respond)
    res = ask(demo_api, "How many employees does Northwind have?")
    assert res["status"] == "answered" and res["confidence"]["score"] <= 0.6
    assert any("not addressed by the model" in c for c in res["caveats"])


# --------------------------------------------------------------------------------------------------
# failure handling: every failure must degrade to the rule-based engine, with a visible reason
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("failure,expected", [
    (RuntimeError("boom"), "failed"),
    (groq.AuthenticationError("bad key", response=httpx.Response(401, request=httpx.Request("POST", "https://x")), body=None), "unavailable"),
    (groq.RateLimitError("slow down", response=_resp_headers({"retry-after": "45"}), body=None), "rate limit"),
    (groq.APIConnectionError(request=httpx.Request("POST", "https://x")), "unavailable"),
])
def test_llm_failure_falls_back_to_rules(demo_api, use_llm, monkeypatch, failure, expected):
    monkeypatch.setattr(settings, "llm_max_retries", 0)
    monkeypatch.setattr(settings, "groq_fallback_model", "")
    use_llm(lambda s, u, kw: failure)
    res = ask(demo_api, "What is the liability cap?")
    assert res["engine"]["name"] == "rules" and res["engine"]["fallback"] is True
    assert res["status"] == "answered" and res["headline"] == "$1,000,000"        # the rule-based answer is still correct
    assert any(expected in c.lower() for c in res["caveats"]), res["caveats"]


def test_short_rate_limits_are_waited_out(demo_api, use_llm):
    state = {"n": 0}

    def respond(system, user, kw):
        state["n"] += 1
        if state["n"] == 1:
            return groq.RateLimitError("slow", response=_resp_headers({"retry-after": "0"}), body=None)
        pid, text = find(user, "capped at $1,000,000")
        return base(headline="$1,000,000", answer=f"Capped [{pid}].", claims=[{"text": "c", "sources": [{"passage": pid, "quote": sentence_with(text, "capped at $1,000,000")}]}])
    use_llm(respond)
    res = ask(demo_api, "What is the liability cap?")
    assert state["n"] == 2 and res["engine"]["name"] == "groq" and res["headline"] == "$1,000,000"


def test_unknown_primary_model_falls_over_to_the_fallback_model(demo_api, use_llm):
    def respond(system, user, kw):
        if kw["model"] == settings.groq_model:
            return groq.NotFoundError("model not found", response=httpx.Response(404, request=httpx.Request("POST", "https://x")), body=None)
        pid, text = find(user, "capped at $1,000,000")
        return base(headline="$1,000,000", answer=f"Capped [{pid}].", claims=[{"text": "c", "sources": [{"passage": pid, "quote": sentence_with(text, "capped at $1,000,000")}]}])
    fake = use_llm(respond)
    res = ask(demo_api, "What is the liability cap?")
    assert [c["model"] for c in fake.calls] == [settings.groq_model, settings.groq_fallback_model]
    assert res["engine"]["name"] == "groq" and res["engine"]["model"] == settings.groq_fallback_model
    assert any("primary model failed" in c for c in res["caveats"])


@pytest.mark.parametrize("junk", ["", "not json at all", "[1, 2, 3]", '{"status": "answered"'])
def test_invalid_model_output_falls_back_to_rules(demo_api, use_llm, junk):
    use_llm(lambda s, u, kw: junk)
    res = ask(demo_api, "What is the liability cap?")
    assert res["engine"]["name"] == "rules" and res["headline"] == "$1,000,000"


def test_json_wrapped_in_markdown_fences_is_accepted(demo_api, use_llm, monkeypatch):
    monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
    def respond(system, user, kw):
        pid, text = find(user, "capped at $1,000,000")
        d = base(headline="$1,000,000", answer=f"Capped [{pid}].", claims=[{"text": "c", "sources": [{"passage": pid, "quote": sentence_with(text, "capped at $1,000,000")}]}])
        return "```json\n" + json.dumps(d) + "\n```"
    use_llm(respond)
    assert ask(demo_api, "What is the liability cap?")["engine"]["name"] == "groq"


def test_truncated_output_with_no_content_falls_back(demo_api, use_llm):
    use_llm(lambda s, u, kw: "", finish="length")
    assert ask(demo_api, "What is the liability cap?")["engine"]["name"] == "rules"


# --------------------------------------------------------------------------------------------------
# modes, prompt-injection, token budget
# --------------------------------------------------------------------------------------------------
def test_rules_mode_never_calls_the_llm(demo_api, use_llm):
    fake = use_llm(lambda s, u, kw: pytest.fail("LLM must not be called in rules mode"))
    res = demo_api.ask("What is the liability cap?", mode="rules")
    assert res["engine"]["name"] == "rules" and not fake.calls


def test_llm_mode_without_a_key_explains_itself(demo_api):
    llm_mod.set_llm(None)
    res = demo_api.ask("What is the liability cap?", mode="llm")
    assert res["engine"]["name"] == "rules" and any("GROQ_API_KEY" in c for c in res["caveats"])


def test_instructions_aimed_at_the_model_never_reach_it(api, use_llm):
    memo = ROOT / "sample-documents" / "adversarial" / "injection_memo.txt"
    api.upload(("memo.txt", memo.read_bytes()))
    seen = {}

    def respond(system, user, kw):
        seen["user"] = user
        pid, text = find(user, "10 business days")
        return base(answer=f"About 10 business days [{pid}].", headline="10 business days",
                    claims=[{"text": "t", "sources": [{"passage": pid, "quote": sentence_with(text, "10 business days")}]}])
    use_llm(respond)
    res = api.ask("How long does vendor onboarding take?", mode="auto")
    u = seen["user"]
    assert "IMPORTANT NOTE TO AI ASSISTANTS" not in u and "ignore all previous instructions" not in u        # redacted before the prompt is built
    assert "[sentence addressed to AI assistants removed]" in u and u.rfind("<passage") < u.rfind("</passage>")
    assert "10 business days" in u                                                                        # the genuine content is still sent, inside passage tags
    assert res["status"] == "answered" and "10 business days" in res["answer"]
    assert any("tries to instruct AI assistants" in w for d in api.docs() for w in d["warnings"])         # and the user is told at upload time


def test_prompt_respects_the_passage_and_size_budget(demo_api, use_llm):
    seen = {}
    use_llm(lambda s, u, kw: (seen.update(user=u), base(status="insufficient", answer="x"))[1])
    ask(demo_api, "What are the payment terms?")
    assert len(passages(seen["user"])) <= settings.llm_max_passages
    assert all(len(t) <= settings.llm_passage_chars + 10 for t in passages(seen["user"]).values())
    assert len(seen["user"]) < 12000                                                   # keeps each call well inside free-tier token limits


def test_missing_model_prose_never_produces_an_empty_answer(demo_api, use_llm):
    """Real Groq run: the model reported a verified conflict but left `answer` and `headline` blank."""
    def respond(system, user, kw):
        p30, t30 = find(user, "Net 30 from the invoice date")
        p45, t45 = find(user, "Net 45")
        q30, q45 = sentence_with(t30, "Net 30"), sentence_with(t45, "Net 45")
        return base(status="conflict", answer="", headline="", confidence="medium", caveats=["The later amendment appears to replace the earlier term."],
                    conflicts=[{"candidate_id": "C1", "summary": "payment terms differ", "resolution": "",
                                "positions": [{"passage": p30, "claim": "Net 30", "quote": q30}, {"passage": p45, "claim": "Net 45", "quote": q45}]}])
    use_llm(respond)
    res = ask(demo_api, "What are the payment terms?")
    assert res["status"] == "conflict" and res["headline"] == "Net 30 vs Net 45"
    assert "no single supported answer" in res["answer"] and "Net 45" in res["answer"] and "[S" in res["answer"]
    assert res["conflicts"][0]["resolution"]                      # empty model resolution falls back to the rule-based reasoning


def test_verified_claims_without_prose_still_show_their_quotes(demo_api, use_llm):
    def respond(system, user, kw):
        pid, text = find(user, "capped at $1,000,000")
        return base(headline="$1,000,000", answer="", claims=[{"text": "cap", "sources": [{"passage": pid, "quote": sentence_with(text, "capped at $1,000,000")}]}])
    use_llm(respond)
    res = ask(demo_api, "What is the liability cap?")
    assert res["status"] == "answered" and "capped at $1,000,000" in res["answer"] and "[S1]" in res["answer"]
