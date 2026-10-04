# Held-out evaluation: `eval/holdout2/`

Different domain and phrasing from the development corpus. See README for how first-run vs post-fix numbers are reported.

### Lexical retrieval (BM25 + char n-grams) - offline extractive engine

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **77%** (10/13) |
| Conflict questions answered with *all* positions + sources | 50% |
| Single-answer questions answered correctly | 75% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 50% / 100% (1 disputed points found, 2 in ground truth) |
| Mean answer latency | 4 ms |

Failures:

- `When is the project due to be completed?` expected **conflict**, got **insufficient** (Low 0.14)
- `What is the daily rate for an excavator?` expected **answered**, got **answered** (High 0.97)
- `What are the maximum working hours per day?` expected **answered**, got **answered** (High 0.97)

Missed conflicts: ['deadline']; false positives: none
