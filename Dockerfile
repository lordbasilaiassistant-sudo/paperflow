FROM python:3.11-slim

# System dependency: Tesseract, used to OCR scans and phone photos. Digital PDFs
# work without it, but real users upload images, so it ships in the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (the web app only — evals/tests aren't needed to serve).
COPY app ./app

# Uploads, rendered page previews, and the SQLite db all live under DATA_DIR.
# Mount a persistent volume here to keep data across restarts/redeploys; without
# one, the ledger resets whenever the container is recreated.
ENV DATA_DIR=/app/data

# Most PaaS hosts inject $PORT; default to 8000 for a plain `docker run`.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
