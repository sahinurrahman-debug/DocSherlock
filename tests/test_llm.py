"""Claude answer path, exercised with a fake client: grounding enforcement must hold even if the model misbehaves."""
import json
import re
from types import SimpleNamespace

import pytest

from investigator import config


class FakeClient:
    """Mimics anthropic.Anthropic().messages.create; `responder(prompt) -> dict | Exception`."""

    def __init__(self, responder, stop_reason="end_turn"):
        self.responder, self.stop_reason, self.calls = responder, stop_reason, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        out = self.responder(kw["messages"][0]["content"])
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=json.dumps(out))])


def passages(prompt):
    return {m.group(1): m.group(3) for m in re.finditer(r'<passage id="(P\d+)" ([^>]*)>\n(.*?)\n</passage>', prompt, re.S)}


def find(prompt, needle):
    for pid, text in passages(prompt).items():
        if needle in text:
            return pid, text
    raise AssertionError(f"{needle!r} not in prompt")


def base(**kw):
    d = {"status": "answered", "headline": "", "answer": "", "confidence": "high", "claims": [], "conflicts": [],
         "dismissed_candidates": [], "caveats": []}
    d.update(kw)
    return d


def sentence_with(text, needle):
    return next(s for s in re.split(r"(?<=[.])\s+", text) if needle in s)


def test_conflict_adjudication_with_verified_quotes(demo_engine):
    def respond(prompt):
        p30, t30 = find(prompt, "Net 30 from the invoice date")
        p45, t45 = find(prompt, "Net 45")
        return base(status="conflict", headline="Net 30 vs Net 45", confidence="high",
                    answer=f"The contract says Net 30 [{p30}] but the amendment says Net 45 [{p45}].",
                    claims=[{"text": "Net 30", "sources": [{"passage": p30, "quote": sentence_with(t30, "Net 30")}]},
                            {"text": "Net 45", "sources": [{"passage": p45, "quote": sentence_with(t45, "Net 45")}]}],
                    conflicts=[{"candidate_id": "C1", "summary": "Payment terms differ between contract and amendment",
                                "positions": [{"passage": p30, "claim": "Net 30", "quote": sentence_with(t30, "Net 30")},
                                              {"passage": p45, "claim": "Net 45", "quote": sentence_with(t45, "Net 45")}],
                                "resolution": "The amendment is later and says it amends Section 3."}])
    client = FakeClient(respond)
    res = demo_engine.ask("What are the payment terms?", llm_client=client)
    assert res["engine"] == "claude" and res["status"] == "conflict"
    assert {p["value"] for p in res["conflicts"][0]["positions"]} == {"Net 30", "Net 45"}
    assert all(c["verified"] for c in res["citations"])
    assert "[S1]" in res["answer"] and "[P" not in res["answer"]                # model ids mapped to verified citations
    assert any("verified verbatim" in r["text"] for r in res["confidence"]["reasons"])
    # request shape: JSON-schema output, explicit effort, system prompt forbidding outside knowledge / following passages
    kw = client.calls[0]
    assert kw["model"] == config.LLM_MODEL
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["output_config"]["effort"] == config.LLM_EFFORT
    assert "untrusted" in kw["system"] and "Use ONLY the passages" in kw["system"]
    assert "<rule_engine_conflict_candidates>" in kw["messages"][0]["content"]


def test_fabricated_quotes_are_discarded_and_answer_withheld(demo_engine):
    def respond(prompt):
        pid, _ = find(prompt, "Net 45")
        return base(answer=f"Payment is due Net 90 [{pid}].", headline="Net 90",
                    claims=[{"text": "Net 90", "sources": [{"passage": pid, "quote": "Invoices are payable Net 90 from the invoice date."}]}])
    res = demo_engine.ask("What are the payment terms?", llm_client=FakeClient(respond))
    assert res["status"] == "insufficient"
    assert not any(c["role"] == "support" for c in res["citations"])
    assert any("verified" in c or "withheld" in c for c in res["caveats"])


def test_partially_fabricated_support_lowers_confidence(demo_engine):
    def respond(prompt):
        pid, text = find(prompt, "capped at $1,000,000")
        good = sentence_with(text, "capped at $1,000,000")
        return base(headline="$1,000,000", answer=f"Liability is capped at $1,000,000 [{pid}].",
                    claims=[{"text": "cap", "sources": [{"passage": pid, "quote": good},
                                                         {"passage": pid, "quote": "Liability is unlimited for data breaches."}]}])
    clean = demo_engine.ask("What is the liability cap?", llm_client=FakeClient(lambda p: (lambda pid_t: base(
        headline="$1,000,000", answer=f"Capped [{pid_t[0]}].",
        claims=[{"text": "cap", "sources": [{"passage": pid_t[0], "quote": sentence_with(pid_t[1], "capped at $1,000,000")}]}]))(find(p, "capped at $1,000,000"))))
    dirty = demo_engine.ask("What is the liability cap?", llm_client=FakeClient(respond))
    assert dirty["confidence"]["score"] < clean["confidence"]["score"]
    assert any("could not be verified" in r["text"] for r in dirty["confidence"]["reasons"])


def test_unverifiable_conflict_claim_is_downgraded(demo_engine):
    def respond(prompt):
        pid, text = find(prompt, "Net 45")
        return base(status="conflict", answer="Sources disagree.", confidence="medium",
                    claims=[{"text": "x", "sources": [{"passage": pid, "quote": sentence_with(text, "Net 45")}]}],
                    conflicts=[{"candidate_id": None, "summary": "made up", "resolution": "",
                                "positions": [{"passage": pid, "claim": "Net 45", "quote": sentence_with(text, "Net 45")},
                                              {"passage": pid, "claim": "Net 12", "quote": "Payment is Net 12 days after delivery."}]}])
    res = demo_engine.ask("What are the payment terms?", llm_client=FakeClient(respond))
    assert res["status"] != "conflict" or len(res["conflicts"][0]["positions"]) >= 2
    assert any("could not be verified" in c or "no verifiable pair" in c for c in res["caveats"])


def test_model_can_dismiss_a_rule_engine_candidate(demo_engine):
    def respond(prompt):
        pid, text = find(prompt, "Net 45")
        q = sentence_with(text, "Net 45")
        return base(answer=f"Per the amendment, Net 45 [{pid}].", headline="Net 45", confidence="medium",
                    claims=[{"text": "Net 45", "sources": [{"passage": pid, "quote": q}]}],
                    dismissed_candidates=[{"candidate_id": "C1", "reason": "the amendment explicitly replaces the original term"}])
    res = demo_engine.ask("What are the payment terms?", llm_client=FakeClient(respond))
    assert res["status"] == "answered" and res["conflicts"] == []
    assert any("judged not to be real" in c for c in res["caveats"])


@pytest.mark.parametrize("failure", [RuntimeError("boom"), TimeoutError("slow")])
def test_llm_failure_falls_back_to_extractive(demo_engine, failure):
    res = demo_engine.ask("What is the liability cap?", llm_client=FakeClient(lambda p: failure))
    assert res["engine"] == "extractive" and res["status"] == "answered" and res["headline"] == "$1,000,000"
    assert any("unavailable" in c for c in res["caveats"])


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_refusal_or_truncation_falls_back(demo_engine, stop):
    res = demo_engine.ask("What is the liability cap?", llm_client=FakeClient(lambda p: base(), stop_reason=stop))
    assert res["engine"] == "extractive" and res["status"] == "answered"


def test_prompt_wraps_documents_as_data_and_includes_injection_text_only_inside_passages(engine):
    from pathlib import Path
    memo = Path(config.ROOT / "samples" / "adversarial" / "injection_memo.txt")
    engine.ingest("memo.txt", memo.read_bytes())
    seen = {}

    def respond(prompt):
        seen["prompt"] = prompt
        pid, text = find(prompt, "10 business days")
        return base(answer=f"About 10 business days [{pid}].", headline="10 business days",
                    claims=[{"text": "t", "sources": [{"passage": pid, "quote": sentence_with(text, "10 business days")}]}],
                    caveats=["A passage contains instructions addressed to an AI assistant; they were ignored."])
    res = engine.ask("How long does vendor onboarding take?", llm_client=FakeClient(respond))
    inj = seen["prompt"].index("IMPORTANT NOTE TO AI ASSISTANTS")
    assert seen["prompt"].rfind("<passage", 0, inj) > seen["prompt"].rfind("</passage>", 0, inj)   # inside a passage block
    assert res["status"] == "answered" and "10 business days" in res["answer"]
    assert any("instructions" in c for c in res["caveats"])


def test_offline_mode_never_calls_llm(demo_engine):
    client = FakeClient(lambda p: pytest.fail("LLM must not be called in offline mode"))
    res = demo_engine.ask("What is the liability cap?", mode="offline", llm_client=client)
    assert res["engine"] == "extractive" and not client.calls
