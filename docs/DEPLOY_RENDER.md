# Deploying DocSherlock on Render

One Render **web service** (Docker) serves the API *and* the built React app. Two ways to run it:

| | **A. Everything free** (default `render.yaml`) | **B. Full retrieval** (paid) |
|---|---|---|
| Web service | Render **free** (512 MB) | Render Standard (2 GB) |
| Database | **Neon** free PostgreSQL | Render PostgreSQL or Neon |
| Vector store | none (keyword retrieval) | Qdrant Cloud free 1 GB |
| LLM | Groq free tier | Groq |
| Setting | `LOW_MEMORY=true` | `LOW_MEMORY=false` |

Plan names, limits and prices change - check each provider's pricing page.

> The Dockerfile, `docker-compose.yml` and `render.yaml` were syntax-validated but the image was **not built** in the authoring environment (the Docker daemon was not running).
> Do step 0 once - it catches problems in minutes instead of during a deploy.

## A. The all-free path (step by step)

**What you give up:** semantic (embedding) search and the cross-encoder reranker are off; retrieval is BM25 + character n-grams. On the evaluation sets the reranker was
accuracy-neutral and the keyword-mode answers stayed correct. Everything else - OCR, conflict detection, comparison, LLM answers with verified quotes - works.
**What you accept:**
* **Neon storage is 0.5 GB per project** (and 100 compute-hours/month; it scales to zero after ~5 min idle, so the first query after a pause is slower). Measured: loading the 11-file sample set
  stores **~3.3 MB** (2.1 MB of that is the original files kept so the page viewer survives restarts; text, chunks and claims are ~0.2 MB), so 0.5 GB holds on the order of 150 sample sets or a few hundred
  ordinary documents. Nothing limits visitors, so `RETENTION_DAYS=14` (set in `render.yaml`) deletes documents older than that at each start-up - and a free service restarts whenever it wakes.
  Set `RETENTION_DAYS=0` to keep everything. If Neon ever fills, writes fail: delete documents in the app, or upgrade.
* A free Render service sleeps after ~15 minutes idle and needs about a minute to wake; Groq's free tier is rate-limited.

1. **Groq key** - https://console.groq.com/keys → create a key (`gsk_…`). No card needed.
2. **Neon database** - https://neon.com → sign up (no card) → create a project → *Connect* → copy the connection string
   (`postgresql://user:pass@ep-….neon.tech/neondb?sslmode=require`). Render's own free Postgres is not used: Render allows only one free database per workspace and it expires after 30 days.
3. **GitHub** - push the repo (`.env` is git-ignored).
4. **Render** - https://render.com → **New → Blueprint** → pick the repo. `render.yaml` creates the free web service (React UI + API in one container, `LOW_MEMORY=true`, `RETENTION_DAYS=14`).
5. When prompted (or later under *Environment*) set `GROQ_API_KEY` and `DATABASE_URL` (the Neon string; `postgres://` and `postgresql://` are both accepted).
6. First build takes several minutes. Open `https://<service>.onrender.com/health` → expect `status: healthy`, `database.engine: postgresql`, `vector_store.mode: disabled`, `llm.available: true`.
7. Open the URL → **Load the sample set** → ask *"What are the payment terms?"* (should flag the Net 30 / Net 45 conflict).
8. Before a demo, open the URL a couple of minutes ahead so the instance is awake.

Measured memory with `LOW_MEMORY=true` (11-document sample set incl. scanned PDFs/images): boot ~180 MB, steady ~230 MB, **peak ~360 MB** while OCR-ing. Very large scanned PDFs
will push the peak up; keep demo uploads modest, or set `OCR_ENABLED=false`.

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
| `vector_store.ok: false` | wrong `QDRANT_URL` (needs `https://…:6333`) or API key |
| Header says *Rule-based engine* | `GROQ_API_KEY` missing/empty in the service environment |
| Answers show "rate limit was reached" | Groq free-tier limit - wait a minute, switch to `openai/gpt-oss-20b`, or upgrade |
| `database.ok: false` | check `DATABASE_URL` (Neon string, includes `?sslmode=require`); a sleeping Neon project wakes on the first query |
| Uploaded files stay in QUEUED | worker busy loading models on first start - give it a minute |
