"""Verify your Groq setup end to end (key, model, structured output, quote verification) in ~10 seconds.

    cd backend
    python scripts/check_groq.py            # uses GROQ_API_KEY / GROQ_MODEL from backend/.env or the environment

It never prints your key. Exit code 0 = everything works.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):                       # Windows consoles default to cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
BACKEND = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="docsherlock-groqcheck-"))
os.environ.update({"DATABASE_URL": f"sqlite:///{(TMP / 'c.db').as_posix()}", "QDRANT_URL": "", "QDRANT_PATH": ":memory:", "INGEST_MODE": "sync",
                   "DATA_DIR": str(TMP), "UPLOAD_DIR": str(TMP / "u"), "DENSE_ENABLED": "false", "LOG_LEVEL": "ERROR"})
sys.path.insert(0, str(BACKEND))

from app.core.config import settings                      # noqa: E402
from app.services.llm import LLMClient, LLMError, LLMAuthError, LLMRateLimited, is_strict_model   # noqa: E402

OK, BAD = "\033[32m✓\033[0m", "\033[31m✗\033[0m"


def step(ok: bool, msg: str) -> bool:
    print(f" {OK if ok else BAD} {msg}")
    return ok


def main() -> int:
    print("DocSherlock - Groq check\n")
    if not step(bool(settings.groq_api_key), f"GROQ_API_KEY is set ({'yes, ' + str(len(settings.groq_api_key)) + ' chars' if settings.groq_api_key else 'NO - put it in backend/.env'})"):
        return 1
    print(f"   provider={settings.llm_provider}  model={settings.groq_model}  fallback={settings.groq_fallback_model or '-'}  "
          f"structured={'json_schema (strict)' if is_strict_model(settings.groq_model) else 'json_object'}  effort={settings.groq_reasoning_effort}\n")

    llm = LLMClient()
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "word": {"type": "string"}}, "required": ["ok", "word"], "additionalProperties": False}
    try:
        t = time.perf_counter()
        data, meta = llm.complete_json("Reply with JSON only.", 'Return {"ok": true, "word": "sherlock"}.', schema, name="ping", max_tokens=200)
        step(True, f"model answered in {int((time.perf_counter() - t) * 1000)} ms via {meta.model} ({meta.prompt_tokens}+{meta.completion_tokens} tokens"
                   f"{', primary model unavailable -> fallback used' if meta.fallback_used else ''})")
        step(data.get("ok") is True, f"structured JSON returned: {data}")
    except LLMAuthError:
        step(False, "Groq rejected the key (401). Create a new key at https://console.groq.com/keys")
        return 1
    except LLMRateLimited as exc:
        step(False, f"rate limited right away: {exc}. Free-tier limits are low - wait a minute or upgrade the plan.")
        return 1
    except LLMError as exc:
        step(False, f"call failed: {exc}")
        print("   Tip: check the model id in GROQ_MODEL (https://console.groq.com/docs/models).")
        return 1

    # full pipeline: two contradicting documents -> the model must report a verified conflict
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        h = {"X-Session-Id": "groq-check-session"}
        client.post("/api/documents/upload", headers=h, files=[
            ("files", ("Agreement.txt", b"Dated: March 3, 2023\n# Payment Terms\nInvoices are payable Net 30 from the invoice date.", "text/plain")),
            ("files", ("Amendment.txt", b"Dated: January 15, 2024\n# Payment Terms\nSection 3 is amended so that invoices are payable Net 45 from the invoice date.", "text/plain"))])
        t = time.perf_counter()
        r = client.post("/api/questions", headers=h, json={"question": "What are the payment terms?", "mode": "llm"}).json()
        ms = int((time.perf_counter() - t) * 1000)
        e = r["engine"]
        step(e["name"] == "groq", f"answered by {e['model'] or e['name']} in {ms} ms" + ("" if e["name"] == "groq" else f" - FELL BACK to rules: {e.get('reason') or r['caveats'][:1]}"))
        step(r["status"] == "conflict", f"status={r['status']} level={r['level']} (expected a conflict: Net 30 vs Net 45)")
        vals = {p["value"] for c in r["conflicts"] for p in c["positions"]}
        step(bool(vals), f"positions reported: {sorted(vals)}")
        step(all(c["verified"] for c in r["citations"]) and bool(r["citations"]), f"{len(r['citations'])} citations, all verified verbatim against the source text")
        print("\nAnswer:\n  " + r["answer"].replace("\n", "\n  ")[:600])
        for cl in r["conflicts"]:
            if cl.get("model_assessment"):
                print(f"\nModel's own view of the disagreement (shown to users as an assessment, never as the answer):\n  {cl['model_assessment']}")
        if r["caveats"]:
            print("\nCaveats shown to the user:\n  - " + "\n  - ".join(r["caveats"]))
        if r["status"] != "conflict":
            print("\nNote: the rule engine found Net 30 vs Net 45 across the two documents; DocSherlock reports such firm disagreements even if the model "
                  "calls one document a replacement. If you see this message, please send me this output.")
        ok = e["name"] == "groq" and r["status"] == "conflict"
    print("\n" + ("All good - DocSherlock will use Groq as its main engine." if ok else "Groq works but the end-to-end check did not behave as expected; see above."))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
