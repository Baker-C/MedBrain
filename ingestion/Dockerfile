# Heavy, run-once ingestion image: Unstructured hi_res system dependencies, the batch
# job, and an exit. No port, nothing served. Run locally against hosted Supabase — it
# is a one-time job, not a deployed service (DESIGN.md, Ingestion).
FROM python:3.12-slim

# hi_res needs a PDF renderer (poppler), OCR (tesseract), and the OpenCV runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
# The extraction group lives here and nowhere else: this is the only place hi_res runs.
RUN uv sync --frozen --no-dev --group extraction

COPY . .

# Without this, the job's per-document progress sits in Python's stdout buffer until
# the process exits — a long hi_res run looks hung when its output is piped or logged.
ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "--no-sync", "python", "-m", "pipeline"]
