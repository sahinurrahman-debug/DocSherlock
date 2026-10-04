"""Evaluation harness: answer quality, conflict handling, abstention and grounding on the demo corpus.

    python eval/run_eval.py              # lexical + dense retrieval, offline extractive engine
    python eval/run_eval.py --lexical    # lexical only (what the test-suite uses)
    python eval/run_eval.py --llm        # additionally evaluate the Claude composer (needs ANTHROPIC_API_KEY)

Writes eval/RESULTS.md.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "samples"))

from investigator import config                      # noqa: E402
from investigator.engine import Engine               # noqa: E402


SET = "holdout2" if "--holdout2" in sys.argv else "holdout" if "--holdout" in sys.argv else ""
HOLDOUT = bool(SET)
QDIR = ROOT / "eval" / SET


def load(dense: bool) -> Engine:
    if not config.SAMPLES_DIR.exists():
        import generate_samples
        generate_samples.main()
    eng = Engine(data_dir=tempfile.mkdtemp(), dense=dense)
    if dense:
        eng.dense.warmup(blocking=True)
    if HOLDOUT:
        for p in sorted((QDIR / "corpus").iterdir()):
            eng.ingest(p.name, p.read_bytes())
    else:
        eng.load_demo()
    if dense:
        eng._on_dense_ready()
    return eng


def corpus_conflict_metrics(eng: Engine) -> dict:
    gt = json.loads((QDIR / "ground_truth_conflicts.json").read_text(encoding="utf-8"))
    clusters = eng.conflicts()
    hit, missed = [], []
    matched_clusters = set()
    for g in gt:
        ok = False
        for i, cl in enumerate(clusters):
            docs = {s["doc_name"] for p in cl["positions"] for s in p["sources"]}
            text = " ".join(p["value"] for p in cl["positions"]).lower()
            if set(g["docs"]) <= docs | set(g["docs"]) and len(docs & set(g["docs"])) >= 2 and all(v.lower() in text for v in g["values"]):
                ok = True
                matched_clusters.add(i)
        (hit if ok else missed).append(g["name"])
    false_pos = [clusters[i] for i in range(len(clusters)) if i not in matched_clusters]
    return {"recall": len(hit) / len(gt), "precision": (len(clusters) - len(false_pos)) / max(len(clusters), 1), "missed": missed,
            "false_positives": [" vs ".join(p["value"] for p in c["positions"]) for c in false_pos], "n_clusters": len(clusters), "n_truth": len(gt)}


def run(eng: Engine, mode: str) -> dict:
    qs = json.loads((QDIR / "questions.json").read_text(encoding="utf-8"))
    rows, t_total = [], 0.0
    grounded = total_cites = 0
    for case in qs:
        t = time.perf_counter()
        res = eng.ask(case["q"], mode=mode)
        t_total += time.perf_counter() - t
        status = res["status"]
        exp = case["expect"]
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
            page = next(p for p in eng.get_pages(c["doc_id"]) if p.number == (c["page"] or 1))
            grounded += page.text[c["start"]:c["end"]] == c["quote"] or c.get("verified", False) and c["quote"].strip() in page.text
        rows.append({"q": case["q"], "expect": exp, "got": status, "pass": ok_status and ok_content and ok_docs,
                     "conf": f"{res['confidence']['label']} {res['confidence']['score']:.2f}", "headline": res["headline"]})
    by = lambda e: [r for r in rows if r["expect"] == e]
    return {
        "rows": rows,
        "overall": sum(r["pass"] for r in rows) / len(rows),
        "conflict_q": sum(r["pass"] for r in by("conflict")) / len(by("conflict")),
        "answer_q": sum(r["pass"] for r in by("answered")) / len(by("answered")),
        "abstain_q": sum(r["pass"] for r in by("insufficient")) / len(by("insufficient")),
        "false_conflict": sum(r["got"] == "conflict" for r in rows if r["expect"] != "conflict") / max(len(rows) - len(by("conflict")), 1),
        "false_abstain": sum(r["got"] == "insufficient" for r in by("answered")) / len(by("answered")),
        "grounded": grounded / max(total_cites, 1),
        "n": len(rows), "avg_ms": 1000 * t_total / len(rows),
    }


def render(name: str, m: dict, corpus: dict) -> str:
    out = [f"### {name}", "",
           "| Metric | Result |", "|---|---|",
           f"| Questions passed (status + content + cited sources) | **{m['overall']:.0%}** ({round(m['overall'] * m['n'])}/{m['n']}) |",
           f"| Conflict questions answered with *all* positions + sources | {m['conflict_q']:.0%} |",
           f"| Single-answer questions answered correctly | {m['answer_q']:.0%} |",
           f"| Unanswerable questions correctly refused | {m['abstain_q']:.0%} |",
           f"| False conflicts on non-conflict questions | {m['false_conflict']:.0%} |",
           f"| Wrongly refused answerable questions | {m['false_abstain']:.0%} |",
           f"| Citations whose quote matches the stored page text at the stated offsets | {m['grounded']:.0%} |",
           f"| Corpus-wide conflict recall / precision | {corpus['recall']:.0%} / {corpus['precision']:.0%} ({corpus['n_clusters']} disputed points found, {corpus['n_truth']} in ground truth) |",
           f"| Mean answer latency | {m['avg_ms']:.0f} ms |", ""]
    fails = [r for r in m["rows"] if not r["pass"]]
    if fails:
        out += ["Failures:", ""] + [f"- `{r['q']}` expected **{r['expect']}**, got **{r['got']}** ({r['headline'] or r['conf']})" for r in fails] + [""]
    if corpus["missed"] or corpus["false_positives"]:
        out += [f"Missed conflicts: {corpus['missed'] or 'none'}; false positives: {corpus['false_positives'] or 'none'}", ""]
    return "\n".join(out)


def main():
    args = set(sys.argv[1:])
    if HOLDOUT:
        report = [f"# Held-out evaluation: `eval/{SET}/`", "",
                  "Different domain and phrasing from the development corpus. See README for how first-run vs post-fix numbers are reported.", ""]
    else:
        report = ["# Evaluation results (development set)", "",
                  "Corpus: 11 mixed-format documents (born-digital PDF, scanned PDF, PNG scan, DOCX, EML, MD, TXT, CSV, HTML) with 10 planted disputed points, "
                  "single-source facts and unanswerable questions. 28 questions in `eval/questions.json`; ground truth in `eval/ground_truth_conflicts.json`. "
                  "The system was developed against this set, so treat it as a regression suite - see RESULTS_HOLDOUT.md for generalisation.", ""]
    configs = [("Lexical retrieval (BM25 + char n-grams) - offline extractive engine", False)]
    if "--lexical" not in args:
        configs.append(("Hybrid retrieval (+ BAAI/bge-small-en-v1.5 embeddings) - offline extractive engine", True))
    for name, dense in configs:
        eng = load(dense)
        m = run(eng, "offline")
        c = corpus_conflict_metrics(eng)
        report.append(render(name, m, c))
        print(render(name, m, c))
    if "--llm" in args:
        if not config.llm_available():
            print("ANTHROPIC_API_KEY not set - skipping --llm")
        else:
            eng = load(True)
            m = run(eng, "llm")
            report.append(render(f"Hybrid retrieval + Claude ({config.LLM_MODEL}) with verified quotes", m, corpus_conflict_metrics(eng)))
            print(report[-1])
    target = ROOT / "eval" / (f"RESULTS_{SET.upper()}.md" if SET else "RESULTS.md")
    target.write_text("\n".join(report), encoding="utf-8")
    print("wrote", target.relative_to(ROOT))


if __name__ == "__main__":
    main()
