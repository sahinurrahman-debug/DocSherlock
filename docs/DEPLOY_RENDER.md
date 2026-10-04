# Deploying DocSherlock on Render

One Render **web service** (Docker) serves the API *and* the built React app. Three ways to run it:

| | **A. Free + semantic search** (default `render.yaml`) | **A'. Free, keyword only** | **B. Everything local** (paid, 2 GB) |
|---|---|---|---|
| Web service | Render **free** (512 MB) | Render **free** | Render Standard |
| Database | Neon free PostgreSQL | Neon free | Render PostgreSQL or Neon |
| Embeddings | **Jina API** (hosted, free key) | none | local FastEmbed (bge-small) |
| Vector DB | **Qdrant Cloud** free 1 GB | none | Qdrant Cloud or embedded |
| Reranker | off | off | local cross-encoder |
| LLM | Groq free | Groq free | Groq |
| Memory (measured peak) | ~410 MB | ~360 MB | ~1.0 GB |

Plan names, limits and prices change - check each provider's pricing page.

**Why hosted embeddings?** The local embedding model + reranker peak near 1 GB, which does not fit Render's 512 MB. With `EMBEDDING_API_URL` set, the model runs at the provider and
the 512 MB service only makes HTTPS calls. For the same reason a remote Qdrant is reached with a thin REST client instead of the official `qdrant-client` (which alone costs ~90 MB of RAM).

> The Dockerfile, `docker-compose.yml` and `render.yaml` were syntax-validated but the image was **not built** in the authoring environment (the Docker daemon was not running).
> The hosted-embedding and remote-Qdrant code is tested against in-process fake servers (Qdrant request bodies are validated against the official models) but **has not been run against a live Jina or Qdrant Cloud**.
> After deploying, upload one file and check it says *indexed* - if the API rejects a request, the document carries a warning naming the error and falls back to keyword retrieval.

## A. The all-free path with semantic search (step by step)

**What you give up:** the cross-encoder reranker (it was accuracy-neutral on the evaluation sets). Everything else - OCR, hybrid search with embeddings, conflict detection,
comparison, LLM answers with verified quotes - works.

**What you accept:**
* **Privacy:** document text is sent to Jina (to embed) and stored in Qdrant Cloud and Neon; with a Groq key, questions and retrieved passages go to Groq. Jina's free key is for **non-commercial** use.
* **Qdrant Cloud free clusters are suspended after a week of inactivity** and deleted after four weeks. If the vectors disappear, DocSherlock notices at start-up and re-indexes from Neon automatically (this costs embedding calls).
* **Neon storage is 0.5 GB per project** (and 100 compute-hours/month; it scales to zero after ~5 min idle, so the first query after a pause is slower). Measured: loading the 11-file sample set
  stores **~3.3 MB** (2.1 MB of that is the original files kept so the page viewer survives restarts; text, chunks and claims are ~0.2 MB), so 0.5 GB holds on the order of 150 sample sets or a few hundred
  ordinary documents. Nothing limits visitors, so `RETENTION_DAYS=14` (set in `render.yaml`) deletes documents older than that at each start-up - and a free service restarts whenever it wakes.
  Set `RETENTION_DAYS=0` to keep everything. If Neon ever fills, writes fail: delete documents in the app, or upgrade.
* A free Render service sleeps after ~15 minutes idle and needs about a minute to wake; Groq's and Jina's free tiers are rate-limited.

1. **Groq key** - https://console.groq.com/keys → create a key (`gsk_…`). No card needed.
2. **Jina key** - https://jina.ai/embeddings → copy the free API key (10M tokens, no card).
3. **Qdrant Cloud** - https://cloud.qdrant.io → sign up (no card) → create a **free** cluster → copy the cluster URL (`https://….cloud.qdrant.io:6333`) and create an API key.
4. **Neon database** - https://neon.com → sign up (no card) → create a project → *Connect* → copy the connection string
   (`postgresql://user:pass@ep-….neon.tech/neondb?sslmode=require`). Render's own free Postgres is not used: Render allows only one free database per workspace and it expires after 30 days.
5. **GitHub** - push the repo (`.env` is git-ignored).
6. **Render** - https://render.com → **New → Blueprint** → pick the repo. `render.yaml` creates the free web service (React UI + API in one container).
7. When prompted (or later under *Environment*) set the five secrets: `GROQ_API_KEY`, `EMBEDDING_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `DATABASE_URL`
   (`postgres://` and `postgresql://` are both accepted for the database). Everything else is preset.
8. First build takes several minutes. Open `https://<service>.onrender.com/health` → expect `status: healthy`, `database.engine: postgresql`, `vector_store.mode: server`,
   `models.dense.source: api`, `llm.available: true`.
9. Open the URL → **Load the sample set** → documents should show *indexed* → ask *"What are the payment terms?"* (should flag the Net 30 / Net 45 conflict). The answer's retrieval trace lists `qdrant-dense`.
10. Before a demo, open the URL a couple of minutes ahead so the instance is awake.

Measured memory (11-document sample set incl. scanned PDFs/images, with fake embedding/Qdrant servers so only the app's own footprint is counted): boot ~105 MB, steady ~270 MB, **peak ~410 MB** while OCR-ing -
inside 512 MB but with modest headroom, and measured on Windows/Python 3.14 rather than the Linux/3.12 container. Keep demo uploads modest, or set `OCR_ENABLED=false`.

**Changing the embedding model or `EMBEDDING_DIM`** is safe: the Qdrant collection name includes both, so a new collection is created and documents are re-indexed on the next start-up.
If your provider rejects the `dimensions` field, set `EMBEDDING_API_DIMENSIONS=false` and `EMBEDDING_DIM` to the model's native size.

## A'. Free, keyword only
Delete the `EMBEDDING_*` and `QDRANT_*` entries from `render.yaml` (or leave `EMBEDDING_API_URL` empty). `LOW_MEMORY=true` then turns embeddings off: BM25 + character n-grams retrieval, no vector DB, peak ~360 MB.

## 0. Smoke-test the image locally (recommended)
Start Docker Desktop, then:
```bash
docker build -t docsherlock .
docker run --rm -p 10000:10000 -e GROQ_API_KEY=gsk_... docsherlock      # http://localhost:10000
# or the full stack with Postgres + Qdrant:
GROQ_API_KEY=gsk_... docker compose up --build                          # http://localhost:8000
```
Optionally run the live PostgreSQL test against the compose database:
```bash
TEST_DATABASE_URL=postgresql+psycopg://docsherlock:docsherlock@localhost:5432/docsherlock pytest backend/tests/test_postgres.py
```

## B. Full-retrieval path

### 1. Accounts you need
| Service | Why | What to copy |
|---|---|---|
| **Groq** - https://console.groq.com/keys | main LLM | the API key (`gsk_…`) |
| **Qdrant Cloud** - https://cloud.qdrant.io (free 1 GB cluster) | vector store that survives restarts | cluster URL (`https://….cloud.qdrant.io:6333`) and API key |
| **Render** - https://render.com | hosting + PostgreSQL | - |
| **GitHub** | Render deploys from a repo | push this project |

### 2. Deploy
(Edit `render.yaml`: `plan: standard`, `LOW_MEMORY: "false"`, add `QDRANT_URL` / `QDRANT_API_KEY` entries with `sync: false`, or set them in the dashboard.)

1. Push the repository to GitHub (`.env` is git-ignored - never commit keys).
2. Render dashboard → **New → Blueprint** → choose the repo. Render reads `render.yaml` and proposes the web service `docsherlock`. (For path B you may add a paid Render PostgreSQL to the Blueprint, or keep using Neon.)
3. When prompted (or later under *Environment*), set:

   | Variable | Value |
   |---|---|
   | `GROQ_API_KEY` | your Groq key |
   | `QDRANT_URL` | your Qdrant Cloud URL |
   | `QDRANT_API_KEY` | your Qdrant API key |
   | `DATABASE_URL` | your Neon (or Render PostgreSQL) connection string |
   | `GROQ_MODEL` *(optional)* | `openai/gpt-oss-120b` (default) or `openai/gpt-oss-20b` |

4. **Instance size.** Measured on the 11-document sample set (resident memory of the server process):

   | Configuration | Steady | Peak (while ingesting scans) | Fits |
   |---|---|---|---|
   | default: embeddings + reranker + OCR | ~700 MB | ~1.0 GB | **2 GB** (recommended) |
   | `RERANK_ENABLED=false` | ~530 MB | ~0.9 GB | 1 GB, tight |
   | `DENSE_ENABLED=false` (keyword retrieval) | ~380 MB | ~0.67 GB | 1 GB; 512 MB only if you avoid scanned documents |
   | `DENSE_ENABLED=false` + `OCR_ENABLED=false` | ~300 MB | ~0.3 GB | **512 MB** |
   | **`LOW_MEMORY=true`** (dense + rerank off, OCR on at reduced resolution) | ~230 MB | ~0.36 GB | **512 MB** |

   Larger workspaces grow the numbers (more chunks, more vectors in memory-side indexes). The reranker was accuracy-neutral on the evaluation sets, so
   `RERANK_ENABLED=false` is the cheapest way to save ~180 MB. Scanned documents (OCR) cause the peak. If you must use a 512 MB instance, add
   `DENSE_ENABLED=false` (keyword retrieval only; semantic search and reranking are disabled, everything else works) and `OCR_ENABLED=false` if memory is still tight.
5. First deploy takes several minutes (it downloads models into the image). Health check path: `/health`.
6. Open the service URL → **Load the sample set** → ask *"What are the payment terms?"*

### 3. Verify the deployment
* `GET https://<your-service>.onrender.com/health` → `status: healthy`, `database.engine: postgresql`, `vector_store.mode: server`, `llm.available: true`.
* In the UI header: *Groq · gpt-oss-120b* and *Qdrant* (no "· local").
* Ask a question; the answer card shows **gpt-oss-120b · quotes verified**. If it says *rule-based* with a note, read the note (missing key, rate limit, model name).

## Operating notes
* **Free instances sleep** after inactivity and take a while to wake (and to load the models) - open the app a couple of minutes before a demo, or use an always-on plan.
* **Ephemeral disk:** originals are also stored in PostgreSQL, so the page viewer keeps working after restarts. If Qdrant is wiped, DocSherlock detects the missing vectors at start-up and
  re-indexes automatically (`reconcile_vectors`).
* **One instance only.** The ingestion worker pool and the corpus cache live in-process; do not scale horizontally without moving ingestion to a queue.
* **Groq free tier** is rate-limited; DocSherlock waits out short limits and otherwise falls back to the rule-based engine with a visible note.
* **Privacy:** documents are stored in *your* PostgreSQL (Neon) and, on path B, Qdrant; with a key set, the question and retrieved passages are sent to Groq.

## Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| Build fails at the "Bake the models" step | transient download failure - redeploy; or temporarily remove that step (models then download on first start) |
| Service restarts / "out of memory" | set `LOW_MEMORY=true`, or instance too small → 2 GB, or use a row of the memory table in step 2.4 (`RERANK_ENABLED=false`, `DENSE_ENABLED=false`, `OCR_ENABLED=false`) |
| Document has the warning *Semantic indexing unavailable (EmbeddingAPIError…)* | the embeddings API rejected the request: wrong `EMBEDDING_API_KEY`/model, or the provider does not accept `dimensions` (set `EMBEDDING_API_DIMENSIONS=false` and `EMBEDDING_DIM` to the native size); it is retried at the next start-up |
| `vector_store.ok: false` | wrong `QDRANT_URL` (needs `https://…:6333`) or API key |
| Header says *Rule-based engine* | `GROQ_API_KEY` missing/empty in the service environment |
| Answers show "rate limit was reached" | Groq free-tier limit - wait a minute, switch to `openai/gpt-oss-20b`, or upgrade |
| `database.ok: false` | check `DATABASE_URL` (Neon string, includes `?sslmode=require`); a sleeping Neon project wakes on the first query |
| Uploaded files stay in QUEUED | worker busy loading models on first start - give it a minute |
