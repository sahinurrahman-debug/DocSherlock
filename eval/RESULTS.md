# Evaluation results (development set)

Corpus: 11 mixed-format documents (born-digital PDF, scanned PDF, PNG scan, DOCX, EML, MD, TXT, CSV, HTML) with 10 planted disputed points, single-source facts and unanswerable questions. 28 questions in `eval/questions.json`; ground truth in `eval/ground_truth_conflicts.json`. The system was developed against this set, so treat it as a regression suite - see RESULTS_HOLDOUT.md for generalisation.

### Lexical retrieval (BM25 + char n-grams) - offline extractive engine

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **100%** (28/28) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 100% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (10 disputed points found, 10 in ground truth) |
| Mean answer latency | 5 ms |

### Hybrid retrieval (+ BAAI/bge-small-en-v1.5 embeddings) - offline extractive engine

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **100%** (28/28) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 100% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (10 disputed points found, 10 in ground truth) |
| Mean answer latency | 107 ms |
