# Held-out evaluation: `eval/holdout/`

Run through the real HTTP API (FastAPI + SQLAlchemy + Qdrant). Rule-based answers unless noted.

### Lexical only (BM25 + char n-grams)

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **100%** (15/15) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 100% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (5 disputed points, 5 in ground truth) |
| Mean answer latency | 183 ms |

### Hybrid: + Qdrant dense & sparse vectors (bge-small, BM25)

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **100%** (15/15) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 100% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (5 disputed points, 5 in ground truth) |
| Mean answer latency | 156 ms |

### Hybrid + cross-encoder reranker (MiniLM)

| Metric | Result |
|---|---|
| Questions passed (status + content + cited sources) | **100%** (15/15) |
| Conflict questions answered with *all* positions + sources | 100% |
| Single-answer questions answered correctly | 100% |
| Unanswerable questions correctly refused | 100% |
| False conflicts on non-conflict questions | 0% |
| Wrongly refused answerable questions | 0% |
| Citations whose quote matches the stored page text at the stated offsets | 100% |
| Corpus-wide conflict recall / precision | 100% / 100% (5 disputed points, 5 in ground truth) |
| Mean answer latency | 1361 ms |
