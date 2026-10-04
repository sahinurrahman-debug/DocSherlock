"""Evaluation harness: answer quality, conflict handling, abstention and grounding - through the real HTTP API.

    python eval/run_eval.py                    # dev corpus; lexical vs hybrid vs hybrid+rerank (rule-based answers)
    python eval/run_eval.py --holdout          # held-out corpus 1 (lab safety / grants)
    python eval/run_eval.py --holdout2         # held-out corpus 2 (civil engineering)
    python eval/run_eval.py --quick            # lexical config only
    python eval/run_eval.py --llm              # additionally evaluate the Groq composer (needs GROQ_API_KEY; ~1 call per question)

Writes eval/RESULTS*.md.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="docsherlock-eval-"))
os.environ.update({"DATABASE_URL": f"sqlite:///{(TMP / 'eval.db').as_posix()}", "QDRANT_URL": "", "QDRANT_PATH": ":memory:", "INGEST_MODE": "sync",
                   "DATA_DIR": str(TMP), "UPLOAD_DIR": str(TMP / "uploads"), "LOG_LEVEL": "ERROR", "DENSE_ENABLED": "false", "RERANK_ENABLED": "false"})
if "--llm" not in sys.argv:
    os.environ["GROQ_API_KEY"] = ""          # rule-based runs never touch the LLM; with --llm the key comes from the shell or backend/.env
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "sample-documents"))

from fastapi.testclient import TestClient            # noqa: E402

from app.core.config import settings                 # noqa: E402
from app.main import app                             # noqa: E402
from app.services import embeddings as emb_mod       # noqa: E402

SET = "holdout2" if "--holdout2" in sys.argv else "holdout" if "--holdout" in sys.argv else ""
QDIR = ROOT / "eval" / SET
CORPUS = QDIR / "corpus" if SET else ROOT / "sample-documents" / "corpus"


def configure(dense: bool, rerank: bool) -> None:
    settings.dense_enabled, settings.rerank_enabled = dense, rerank
    svc = emb_mod.EmbeddingService()
    emb_mod._service = svc
    if dense:
        svc.warmup(blocking=True)


def load(client: TestClient) -> dict:
    if not CORPUS.exists():
        import generate
        generate.main()
    session = f"eval-{uuid.uuid4().hex[:10]}"
    h = {"X-Session-Id": session}
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in sorted(CORPUS.iterdir()) if p.is_file()]
    r = client.post("/api/documents/upload", files=files, headers=h)
    assert r.status_code == 202
    bad = [(d["filename"], d["error"]) for d in client.get("/api/documents", headers=h).json() if d["status"] != "READY"]
    assert not bad, bad
    return h


def corpus_conflict_metrics(client: TestClient, h: dict) -> dict:
    gt = json.loads((QDIR / "ground_truth_conflicts.json").read_text(encoding="utf-8"))
    clusters = client.get("/api/conflicts", headers=h).json()["conflicts"]
    hit, missed, matched = [], [], set()
    for g in gt:
        ok = False
        for i, cl in enumerate(clusters):
            docs = {s["doc_name"] for p in cl["positions"] for s in p["sources"]}
            text = " ".join(p["value"] for p in cl["positions"]).lower()
            if len(docs & set(g["docs"])) >= 2 and all(v.lower() in text for v in g["values"]):
                ok = True
                matched.add(i)
        (hit if ok else missed).append(g["name"])
    fp = [clusters[i] for i in range(len(clusters)) if i not in matched]
    return {"recall": len(hit) / len(gt), "precision": (len(clusters) - len(fp)) / max(len(clusters), 1), "missed": missed,
            "false_positives": [" vs ".join(p["value"] for p in c["positions"]) for c in fp], "n_clusters": len(clusters), "n_truth": len(gt)}


def run(client: TestClient, h: dict, mode: str) -> dict:
    qs = json.loads((QDIR / "questions.json").read_text(encoding="utf-8"))
    rows, t_total, grounded, total_cites = [], 0.0, 0, 0
    page_cache: dict[tuple, str] = {}
    fallbacks = 0
    for case in qs:
        for attempt in range(4):
            t = time.perf_counter()
            res = client.post("/api/questions", json={"question": case["q"], "mode": mode}, headers=h).json()
            elapsed = time.perf_counter() - t
            limited = res["engine"]["fallback"] and any("rate limit" in c.lower() for c in res["caveats"])
            if mode == "rules" or not limited or attempt == 3:
                break
            print(f"  rate limited on {case['q']!r} - waiting 40 s and retrying ({attempt + 1}/3)", flush=True)
            time.sleep(40)                                                   # a rate-limited answer is not a measurement of the model
        t_total += elapsed
        if mode != "rules":                                                  # pace by tokens: stay under the free tier's tokens-per-minute budget
            tok = res["engine"].get("tokens") or {}
            used = (tok.get("prompt", 0) + tok.get("completion", 0)) or 0
            time.sleep(max(2.0, used * 60 / float(os.environ.get("EVAL_TPM", "6000")) - elapsed))
        fallbacks += int(res["engine"]["fallback"])
        status, exp = res["status"], case["expect"]
        ok_status = status in ("answered", "partial") if exp == "answered" else status == exp
        ok_content = True
        if exp == "answered":
            if "headline" in case:
                ok_content = res["headline"] == case["headline"]
            for s in case.get("contains", []):
                ok_content &= s.lower() in res["answer"].lower()
        if exp == "conflict":
            shown = (" ".join(p["value"] for cl in res["conflicts"] for p in cl["positions"]) + " " + res["answer"]).lower()
            ok_content = all(v.lower() in shown for v in case["values"])
        cited = {c["doc_name"] for c in res["citations"] if c["role"] != "lead"}
        ok_docs = set(case.get("docs", [])) <= cited if exp != "insufficient" else not any(c["role"] == "support" for c in res["citations"])
        for c in res["citations"]:
            total_cites += 1
            key = (c["doc_id"], c["page"] or 1)
            if key not in page_cache:
                page_cache[key] = client.get(f"/api/documents/{key[0]}/pages/{key[1]}", headers=h).json()["page"]["text"]
            grounded += page_cache[key][c["start"]:c["end"]] == c["quote"]
        rows.append({"q": case["q"], "expect": exp, "got": status, "pass": ok_status and ok_content and ok_docs, "level": res["level"],
                     "headline": res["headline"], "engine": res["engine"]["name"]})
    by = lambda e: [r for r in rows if r["expect"] == e]
    return {
        "rows": rows, "n": len(rows), "overall": sum(r["pass"] for r in rows) / len(rows),
        "conflict_q": sum(r["pass"] for r in by("conflict")) / max(len(by("conflict")), 1),
        "answer_q": sum(r["pass"] for r in by("answered")) / max(len(by("answered")), 1),
        "abstain_q": sum(r["pass"] for r in by("insufficient")) / max(len(by("insufficient")), 1),
        "false_conflict": sum(r["got"] == "conflict" for r in rows if r["expect"] != "conflict") / max(len(rows) - len(by("conflict")), 1),
        "false_abstain": sum(r["got"] == "insufficient" for r in by("answered")) / max(len(by("answered")), 1),
        "grounded": grounded / max(total_cites, 1), "avg_ms": 1000 * t_total / len(rows), "fallbacks": fallbacks,
    }


def render(name: str, m: dict, corpus: dict) -> str:
    out = [f"### {name}", "", "| Metric | Result |", "|---|---|",
           f"| Questions passed (status + content + cited sources) | **{m['overall']:.0%}** ({round(m['overall'] * m['n'])}/{m['n']}) |",
           f"| Conflict questions answered with *all* positions + sources | {m['conflict_q']:.0%} |",
           f"| Single-answer questions answered correctly | {m['answer_q']:.0%} |",
           f"| Unanswerable questions correctly refused | {m['abstain_q']:.0%} |",
           f"| False conflicts on non-conflict questions | {m['false_conflict']:.0%} |",
           f"| Wrongly refused answerable questions | {m['false_abstain']:.0%} |",
           f"| Citations whose quote matches the stored page text at the stated offsets | {m['grounded']:.0%} |",
           f"| Corpus-wide conflict recall / precision | {corpus['recall']:.0%} / {corpus['precision']:.0%} ({corpus['n_clusters']} disputed points, {corpus['n_truth']} in ground truth) |",
           f"| Mean answer latency | {m['avg_ms']:.0f} ms |"]
    if m["fallbacks"]:
        out.append(f"| Answers that fell back to the rule-based engine | {m['fallbacks']} |")
    out.append("")
    fails = [r for r in m["rows"] if not r["pass"]]
    if fails:
        out += ["Failures:", ""] + [f"- `{r['q']}` expected **{r['expect']}**, got **{r['got']}** ({r['headline'] or r['level']})" for r in fails] + [""]
    if corpus["missed"] or corpus["false_positives"]:
        out += [f"Missed conflicts: {corpus['missed'] or 'none'}; false positives: {corpus['false_positives'] or 'none'}", ""]
    return "\n".join(out)


def main() -> None:
    args = set(sys.argv[1:])
    title = f"Held-out evaluation: `eval/{SET}/`" if SET else "Evaluation results (development set)"
    report = [f"# {title}", "", "Run through the real HTTP API (FastAPI + SQLAlchemy + Qdrant). Rule-based answers unless noted.", ""]
    configs = [("Lexical only (BM25 + char n-grams)", False, False, "rules")]
    if "--quick" not in args:
        configs += [("Hybrid: + Qdrant dense & sparse vectors (bge-small, BM25)", True, False, "rules"),
                    ("Hybrid + cross-encoder reranker (MiniLM)", True, True, "rules")]
    if "--llm" in args:
        if not settings.llm_available:
            print("GROQ_API_KEY not set - skipping --llm")
        else:
            configs.append((f"Hybrid + reranker + Groq `{settings.groq_model}` (LLM main, rules fallback)", True, True, "auto"))
    with TestClient(app) as client:
        for name, dense, rerank, mode in configs:
            configure(dense, rerank)
            h = load(client)
            m = run(client, h, mode)
            c = corpus_conflict_metrics(client, h)
            text = render(name, m, c)
            report.append(text)
            print(text)
    if "--quick" in args:
        print("(--quick is a partial run: the report file was not overwritten)")
        return
    target = ROOT / "eval" / (f"RESULTS_{SET.upper()}.md" if SET else "RESULTS.md")
    target.write_text("\n".join(report), encoding="utf-8")
    print("wrote", target.relative_to(ROOT))


if __name__ == "__main__":
    main()
