FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DOCINV_DATA_DIR=/data HOST=0.0.0.0 PORT=7860
WORKDIR /app

# onnxruntime / opencv need libgomp + libglib at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# bake the OCR + embedding models into the image so the first request is fast and works offline
RUN python -c "from rapidocr import RapidOCR; RapidOCR()" && \
    python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warm up']))"

COPY investigator ./investigator
COPY samples ./samples
COPY eval ./eval
RUN python samples/generate_samples.py

VOLUME /data
EXPOSE 7860
CMD ["python", "-m", "investigator.main"]
