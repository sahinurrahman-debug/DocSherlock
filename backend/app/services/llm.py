"""LLM client (Groq by default, any OpenAI-compatible endpoint optionally).

* strict JSON-schema output on models that support constrained decoding (gpt-oss, qwen3), `json_object` mode elsewhere;
* rate-limit aware: honours `retry-after` for short waits, otherwise raises so the caller can fall back to the rule engine;
* one automatic retry on the fallback model when the primary model is unknown/decommissioned or returns invalid JSON.
The key lives only in the backend environment - it is never sent to the browser.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from app.core.config import settings

log = logging.getLogger("docsherlock.llm")

STRICT_PREFIXES = ("openai/gpt-oss", "qwen/qwen3")


class LLMError(Exception):
    """Base class - the caller falls back to the rule-based engine."""


class LLMDisabled(LLMError):
    pass


class LLMAuthError(LLMError):
    pass


class LLMRateLimited(LLMError):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class LLMUnavailable(LLMError):
    pass


class LLMBadResponse(LLMError):
    pass


@dataclass
class LLMMeta:
    model: str = ""
    provider: str = ""
    strict: bool = False
    fallback_used: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    notes: list[str] = field(default_factory=list)


def is_strict_model(model: str) -> bool:
    return model.startswith(STRICT_PREFIXES)


def _is_reasoning_model(model: str) -> bool:
    return model.startswith("openai/gpt-oss")


class LLMClient:
    def __init__(self, client=None):
        self._client = client                       # injectable (tests)

    # ---- availability ----------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._client is not None or settings.llm_available

    @property
    def model(self) -> str:
        return settings.groq_model

    def _get(self):
        if self._client is None:
            if not settings.llm_available:
                raise LLMDisabled("No LLM API key configured (set GROQ_API_KEY).")
            from groq import Groq
            kwargs = {"api_key": settings.llm_key, "timeout": settings.llm_timeout_s, "max_retries": 0}
            if settings.llm_provider != "groq" and settings.llm_base_url:
                kwargs["base_url"] = settings.llm_base_url
            self._client = Groq(**kwargs)
        return self._client

    # ---- main entry ------------------------------------------------------------------------
    def complete_json(self, system: str, user: str, schema: dict, name: str = "response", max_tokens: int | None = None) -> tuple[dict, LLMMeta]:
        client = self._get()
        models = [settings.groq_model]
        if settings.groq_fallback_model and settings.groq_fallback_model != settings.groq_model:
            models.append(settings.groq_fallback_model)
        last: Exception | None = None
        for attempt, model in enumerate(models):
            try:
                data, meta = self._call(client, model, system, user, schema, name, max_tokens or settings.llm_max_output_tokens)
                meta.fallback_used = attempt > 0
                if attempt > 0:
                    meta.notes.append(f"primary model failed ({last}); answered by {model}")
                return data, meta
            except (LLMBadResponse, LLMUnavailable) as exc:      # try the fallback model once
                last = exc
                log.warning("LLM attempt with %s failed: %s", model, exc)
                continue
        raise last or LLMUnavailable("LLM call failed")

    # ---- one model, with retries -------------------------------------------------------------
    def _call(self, client, model: str, system: str, user: str, schema: dict, name: str, max_tokens: int) -> tuple[dict, LLMMeta]:
        import groq

        strict = settings.groq_structured == "strict" or (settings.groq_structured == "auto" and is_strict_model(model))
        if settings.groq_structured == "json_object":
            strict = False
        sys_prompt = system
        if strict:
            response_format = {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
        else:
            response_format = {"type": "json_object"}
            sys_prompt += ("\n\nReturn ONLY one JSON object (no prose, no markdown fences) matching this JSON Schema:\n"
                           + json.dumps(schema, separators=(",", ":")))
        kwargs: dict = dict(model=model, messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
                            temperature=0, max_completion_tokens=max_tokens, response_format=response_format)
        if _is_reasoning_model(model):
            kwargs["reasoning_effort"] = settings.groq_reasoning_effort
            kwargs["include_reasoning"] = False
        delay = 0.8
        for attempt in range(settings.llm_max_retries + 1):
            t0 = time.perf_counter()
            try:
                resp = client.chat.completions.create(**kwargs)
            except groq.AuthenticationError as exc:
                raise LLMAuthError("The LLM API key was rejected (check GROQ_API_KEY).") from exc
            except groq.RateLimitError as exc:
                ra = _retry_after(exc)
                if ra is not None and ra <= 6 and attempt < settings.llm_max_retries:
                    log.info("rate limited, waiting %.1fs", ra)
                    time.sleep(ra + 0.2)
                    continue
                raise LLMRateLimited("LLM rate limit reached" + (f" (retry in {ra:.0f}s)" if ra else ""), ra) from exc
            except (groq.APITimeoutError, groq.APIConnectionError, groq.InternalServerError) as exc:
                if attempt < settings.llm_max_retries:
                    time.sleep(delay)
                    delay *= 2.5
                    continue
                raise LLMUnavailable(f"LLM service unreachable: {exc.__class__.__name__}") from exc
            except (groq.BadRequestError, groq.NotFoundError, groq.UnprocessableEntityError, groq.PermissionDeniedError) as exc:
                raise LLMBadResponse(f"{exc.__class__.__name__}: {_short(exc)}") from exc
            except groq.APIStatusError as exc:
                raise LLMUnavailable(f"{exc.__class__.__name__}: {_short(exc)}") from exc

            choice = resp.choices[0]
            finish = getattr(choice, "finish_reason", None)
            text = (choice.message.content or "").strip()
            if finish == "length" and not text:
                raise LLMBadResponse("model hit the output limit before producing an answer")
            data = _parse_json(text)
            usage = getattr(resp, "usage", None)
            meta = LLMMeta(model=model, provider=settings.llm_provider, strict=strict,
                           prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0, completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                           latency_ms=int((time.perf_counter() - t0) * 1000))
            return data, meta
        raise LLMUnavailable("LLM call failed")


def _parse_json(text: str) -> dict:
    if not text:
        raise LLMBadResponse("empty model response")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        out = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise LLMBadResponse("model response was not JSON")
        try:
            out = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise LLMBadResponse("model response was not valid JSON") from exc
    if not isinstance(out, dict):
        raise LLMBadResponse("model response was not a JSON object")
    return out


def _retry_after(exc) -> float | None:
    try:
        v = exc.response.headers.get("retry-after")
        return float(v) if v is not None else None
    except Exception:
        return None


def _short(exc, n: int = 160) -> str:
    msg = str(getattr(exc, "message", None) or exc)
    return msg[:n]


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def set_llm(client: LLMClient | None) -> None:
    """Swap the process-wide client (tests inject fakes)."""
    global _client
    _client = client
