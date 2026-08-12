# Ingestion

A run-once batch job: the corpus PDFs in the private Supabase Storage bucket become
embedded, cited chunks in pgvector. It starts, reconciles, prints what it did, and
exits — no port, nothing served.

It is **not** deployed. The backend and frontend run on Render; this runs on your
machine and writes into the same hosted Supabase. The two never talk directly — they
meet at the database and the bucket.

## Running it

Three prerequisites, in order:

1. **Schema** — the tables belong to the backend. From `backend/`:
   `uv run python -m persistence.migrate`
2. **Bucket** — seed it from the repo's `DocumentCorpus/`, once:
   `uv run scripts/upload/upload_corpus.py`
3. **Credentials** — `cp .env.example .env` and fill it in. `DATABASE_URL` points at
   Supabase Postgres; `SUPABASE_SERVICE_KEY` is the service role key, used here to
   read the private bucket.

Then, from this directory:

```
docker build -t medbrain-ingestion .
docker run --rm --env-file .env medbrain-ingestion
```

The container exists because `hi_res` needs poppler, tesseract, and OpenCV — a Linux
toolchain that is painful to install on Windows and identical everywhere inside an
image. To run it without Docker: `uv sync --group extraction && uv run python -m pipeline`.

Re-running is safe and cheap. A byte-identical document skips extraction entirely; a
revised one re-embeds only the chunks whose text actually changed.

## What it does

```
bucket → hi_res extraction → clean → carve (pass 1) → split (pass 2) → stamp → embed → reconcile
```

| Module | Role |
|---|---|
| `storage.py` | list and download the bucket |
| `extraction.py` | Unstructured `hi_res` → `PageElement` (the only impure-input module) |
| `cleaning.py` | page furniture, PDF hard wraps, cross-page table stitching |
| `carving.py` | pass 1: the body window, and sections from PLR headings |
| `splitting.py` | pass 2: ~1500 chars per section, headings repeated, pages resolved |
| `tables.py` | `hi_res` table HTML → text, oversized tables split by row groups |
| `stamping.py` | SHA-256 content hash, chunk index, the page floor |
| `identity.py` | one `gpt-5-mini` call per document for drug, manufacturer, formulation |
| `embedding.py` | `text-embedding-3-large` at 1536 dimensions |
| `reconciliation.py` | the corpus and chunk diffs — all of idempotency, as pure functions |
| `registry.py` | the `documents` and `chunks` writes, one transaction per document |
| `pipeline.py` | composes the above; `python -m pipeline` |

Everything from `cleaning` through `reconciliation` is a pure function over typed
values, which is why `tests/` needs no PDF, no database, and no API key.

## Tests

```
uv sync
uv run ruff check . && uv run mypy && uv run pytest
```

`uv sync` without `--group extraction` deliberately skips Unstructured and its CV
model weights: nothing in the test suite imports them, so CI never pays for them.
