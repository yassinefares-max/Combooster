# ==============================================================
# Dockerfile — Flask + Playwright (Chromium) + RAG (cached model)
# ==============================================================
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy
# ---------- Base setup ----------
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
# Copy requirements first (leverages Docker layer cache)
COPY requirements.txt .
# Install Python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt
# Install ONLY Chromium runtime for Playwright
RUN playwright install chromium && \
    playwright install-deps chromium && \
    rm -rf /ms-playwright/firefox* /ms-playwright/webkit*
# ---------- Vendor the embedding model at build-time ----------
# This prevents runtime downloads in production.
# You can change the model if you want (keep in sync with rag_system.py).
ENV EMBEDDING_MODEL_PATH=/app/models/all-MiniLM-L6-v2
RUN python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="sentence-transformers/all-MiniLM-L6-v2",
    local_dir="/app/models/all-MiniLM-L6-v2",
    local_dir_use_symlinks=False,
    ignore_patterns=["*.msgpack", "*.h5", "*.onnx", "tf_model.h5"]
)
print(":coche_blanche: Model snapshot downloaded to /app/models/all-MiniLM-L6-v2")
PY
# ---------- App code ----------
COPY . .
# Clean up caches / docs to reduce size
RUN apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /usr/share/doc/* /usr/share/man/* ~/.cache
# ---------- Runtime env ----------
# Let Flask know which file to run; change if your file is different.
ENV FLASK_ENV=production \
    FLASK_APP=app5.py
EXPOSE 5000
# Use the non-root user provided by the base image
RUN chown -R pwuser:pwuser /app
USER pwuser
# If you persist FAISS index between restarts, it’ll reload instantly
# (rag_system.py writes/reads faiss_index.bin + faiss_metadata.json)
CMD ["python", "app5.py"]