# Held-out evaluation: `eval/holdout2/`

Run through the real HTTP API (FastAPI + SQLAlchemy + Qdrant). Rule-based answers unless noted.

### Lexical only (BM25 + char n-grams)

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **92%** (12/13) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 88% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (2 disputed points, 2 in ground truth) |
| Mean answer latency | 183 ms |

Failures:

- `What are the maximum working hours per day?` expected **answered**, got **answered** (HIGH)

### Hybrid: + Qdrant dense & sparse vectors (bge-small, BM25)

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **92%** (12/13) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 88% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (2 disputed points, 2 in ground truth) |
| Mean answer latency | 132 ms |

Failures:

- `What are the maximum working hours per day?` expected **answered**, got **answered** (HIGH)

### Hybrid + cross-encoder reranker (MiniLM)

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **92%** (12/13) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 88% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (2 disputed points, 2 in ground truth) |
| Mean answer latency | 982 ms |

Failures:

- `What are the maximum working hours per day?` expected **answered**, got **answered** (HIGH)
