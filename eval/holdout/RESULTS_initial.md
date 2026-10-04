# Held-out evaluation (research-lab corpus, written after tuning)

7 documents in a different domain and phrasing (see `eval/holdout/`). Nothing in the system was tuned on this set before the first run.

### Lexical retrieval (BM25 + char n-grams) - offline extractive engine

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **60%** (9/15) |
| Conflict questions answered with *all* positions + sources | 40% |
| Single-answer questions answered correctly | 57% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 43% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 60% / 100% (3 disputed points found, 5 in ground truth) |
| Mean answer latency | 6 ms |

Failures:

- `How often must eyewash stations be tested?` expected **conflict**, got **answered** (High 0.97)
- `What is the spill reporting threshold?` expected **conflict**, got **conflict** (15 minutes vs 30 minutes)
- `How much is the Meridian Foundation grant?` expected **conflict**, got **answered** ($1,250,000)
- `How long is the grant period?` expected **answered**, got **insufficient** (Low 0.00)
- `What is the personnel budget?` expected **answered**, got **insufficient** (Low 0.14)
- `What is the travel budget?` expected **answered**, got **insufficient** (Low 0.13)

Missed conflicts: ['eyewash frequency', 'grant amount']; false positives: none

### Hybrid retrieval (+ BAAI/bge-small-en-v1.5 embeddings) - offline extractive engine

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **60%** (9/15) |
| Conflict questions answered with *all* positions + sources | 40% |
| Single-answer questions answered correctly | 57% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 43% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 60% / 100% (3 disputed points found, 5 in ground truth) |
| Mean answer latency | 5 ms |

Failures:

- `How often must eyewash stations be tested?` expected **conflict**, got **answered** (High 0.97)
- `What is the spill reporting threshold?` expected **conflict**, got **conflict** (15 minutes vs 30 minutes)
- `How much is the Meridian Foundation grant?` expected **conflict**, got **answered** ($1,250,000)
- `How long is the grant period?` expected **answered**, got **insufficient** (Low 0.00)
- `What is the personnel budget?` expected **answered**, got **insufficient** (Low 0.14)
- `What is the travel budget?` expected **answered**, got **insufficient** (Low 0.13)

Missed conflicts: ['eyewash frequency', 'grant amount']; false positives: none
