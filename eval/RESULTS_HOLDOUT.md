# Held-out evaluation: `eval/holdout/`

Different domain and phrasing from the development corpus. See README for how first-run vs post-fix numbers are reported.

### Lexical retrieval (BM25 + char n-grams) - offline extractive engine

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **100%** (15/15) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 100% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (5 disputed points found, 5 in ground truth) |
| Mean answer latency | 10 ms |

### Hybrid retrieval (+ BAAI/bge-small-en-v1.5 embeddings) - offline extractive engine

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **100%** (15/15) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 100% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (5 disputed points found, 5 in ground truth) |
| Mean answer latency | 5 ms |
