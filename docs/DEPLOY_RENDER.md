# Deploying DocSherlock on Render

One Render **web service** (Docker) serves the API *and* the built React app, backed by a Render **PostgreSQL** database and a **Qdrant Cloud** cluster.
Plan names and prices change - check Render's current pricing page before choosing.

> The Dockerfile, `docker-compose.yml` and `render.yaml` were syntax-validated but the image was **not built** in the authoring environment (the Docker daemon was not running).
> Do step 0 once - it catches problems in minutes instead of during a deploy.

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

## 1. Accounts you need
| Service | Why | What to copy |
|---|---|---|
| **Groq** - https://console.groq.com/keys | main LLM | the API key (`gsk_…`) |
| **Qdrant Cloud** - https://cloud.qdrant.io (free 1 GB cluster) | vector store that survives restarts | cluster URL (`https://….cloud.qdrant.io:6333`) and API key |
| **Render** - https://render.com | hosting + PostgreSQL | - |
| **GitHub** | Render deploys from a repo | push this project |

## 2. Deploy
1. Push the repository to GitHub (`.env` is git-ignored - never commit keys).
2. Render dashboard → **New → Blueprint** → choose the repo. Render reads `render.yaml` and proposes: web service `docsherlock` + database `docsherlock-db`.
3. When prompted (or later under *Environment*), set:

   | Variable | Value |
   |---|---|
   | `GROQ_API_KEY` | your Groq key |
   | `QDRANT_URL` | your Qdrant Cloud URL |
   | `QDRANT_API_KEY` | your Qdrant API key |
   | `DATABASE_URL` | filled automatically from `docsherlock-db` |
   | `GROQ_MODEL` *(optional)* | `openai/gpt-oss-120b` (default) or `openai/gpt-oss-20b` |

4. **Instance size.** The embedding model + reranker + OCR need roughly 1-1.5 GB RAM → choose a **2 GB** instance. If you must use a 512 MB instance, add
   `DENSE_ENABLED=false` (keyword retrieval only; semantic search and reranking are disabled, everything else works) and `OCR_ENABLED=false` if memory is still tight.
5. First deploy takes several minutes (it downloads models into the image). Health check path: `/health`.
6. Open the service URL → **Load the sample set** → ask *"What are the payment terms?"*

## 3. Verify the deployment
* `GET https://<your-service>.onrender.com/health` → `status: healthy`, `database.engine: postgresql`, `vector_store.mode: server`, `llm.available: true`.
* In the UI header: *Groq · gpt-oss-120b* and *Qdrant* (no "· local").
* Ask a question; the answer card shows **gpt-oss-120b · quotes verified**. If it says *rule-based* with a note, read the note (missing key, rate limit, model name).

## 4. Operating notes
* **Free instances sleep** after inactivity and take a while to wake (and to load the models) - open the app a couple of minutes before a demo, or use an always-on plan.
* **Ephemeral disk:** originals are also stored in PostgreSQL, so the page viewer keeps working after restarts. If Qdrant is wiped, DocSherlock detects the missing vectors at start-up and
  re-indexes automatically (`reconcile_vectors`).
* **One instance only.** The ingestion worker pool and the corpus cache live in-process; do not scale horizontally without moving ingestion to a queue.
* **Groq free tier** is rate-limited; DocSherlock waits out short limits and otherwise falls back to the rule-based engine with a visible note.
* **Privacy:** documents are stored in *your* Render PostgreSQL and Qdrant; with a key set, the question and retrieved passages are sent to Groq.

## 5. Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| Build fails at the "Bake the models" step | transient download failure - redeploy; or temporarily remove that step (models then download on first start) |
| Service restarts / "out of memory" | instance too small → 2 GB, or `DENSE_ENABLED=false` |
| `vector_store.ok: false` | wrong `QDRANT_URL` (needs `https://…:6333`) or API key |
| Header says *Rule-based engine* | `GROQ_API_KEY` missing/empty in the service environment |
| Answers show "rate limit was reached" | Groq free-tier limit - wait a minute, switch to `openai/gpt-oss-20b`, or upgrade |
| `database.ok: false` | check the `DATABASE_URL` env var is linked to `docsherlock-db` |
| Uploaded files stay in QUEUED | worker busy loading models on first start - give it a minute |
