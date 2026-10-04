# DocSherlock - one image that serves the API and the built React app (ideal for Render / any container host).
# Stage 1: build the React frontend
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/models \
    HOST=0.0.0.0 PORT=10000

# onnxruntime / OpenCV need libgomp, libglib and libGL at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the models into the image so the first request is fast and the container works without outbound model downloads.
RUN python - <<'EOF'
from fastembed import TextEmbedding, SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
list(TextEmbedding("BAAI/bge-small-en-v1.5").embed(["warm up"]))
list(SparseTextEmbedding("Qdrant/bm25").embed(["warm up"]))
list(TextCrossEncoder("Xenova/ms-marco-MiniLM-L-6-v2").rerank("q", ["d"]))
from rapidocr import RapidOCR
RapidOCR()
EOF

COPY backend/ /app/backend/
COPY sample-documents/ /app/sample-documents/
COPY --from=web /web/dist /app/frontend/dist
RUN python /app/sample-documents/generate.py \
 && useradd -m app && mkdir -p /app/backend/data /app/backend/uploads && chown -R app /app /opt/models
USER app

EXPOSE 10000
# One process on purpose: ingestion workers, the corpus cache and embedded-Qdrant mode all live in-process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
