# MedBrain

MedBrain answers a clinical operations professional's natural-language questions over a
corpus of FDA drug labels, and cites every claim back to the document, section, and page
it came from. Answers stream token by token; a citation opens the source PDF at the right
page through a short-lived signed URL. When the corpus does not contain the answer, the
app says so instead of guessing, and it refuses personal-medical-advice questions rather
than answering them.

**Live URL:** <https://medbrain-site.onrender.com/>

The backend is a separate Render service and is not the address you visit. Both are on
Render's free plan, so the first request after an idle period pays a cold start.

Design reasoning lives in [`DESIGN.md`](DESIGN.md). This file is operational only.

## Corpus

17 DailyMed FDA drug-label PDFs covering 10 drugs, checked into
[`DocumentCorpus/`](DocumentCorpus/). Six of the drugs have two or three sibling labels
from different labelers.

## Prerequisites

| Need | Used for |
|---|---|
| [uv](https://docs.astral.sh/uv/) | backend and ingestion Python environments |
| Node 22 | frontend |
| Docker | ingestion only (the `hi_res` PDF toolchain) |
| A Supabase project | Postgres + `pgvector`, and the private corpus bucket |
| An OpenAI API key | embeddings, generation, reranking, eval judge |

There is no Docker Compose — the three projects are run independently with their own
toolchains. The root `Makefile` has exactly one target, `eval`.

## Run it locally

Two commands, one per side, each from its own directory. Fill in `.env` first.

Backend (`backend/`):

```
cp .env.example .env      # then fill in the four values
uv sync
uv run python -m persistence.migrate
uv run uvicorn api.app:create_app --factory --reload
```

Serves on `http://localhost:8000`. `GET /health` is the probe.

Frontend (`frontend/`):

```
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000
npm ci
npm run dev
```

Serves on `http://localhost:5173`, which is also the backend's default
`FRONTEND_ORIGIN`, so CORS works with no extra configuration. `npm run build` fails fast
if `VITE_API_BASE_URL` is unset (`frontend/vite.config.ts`); `npm run dev` does not, but
requests go to `undefined/...` without it, so set it either way.

The app needs an ingested corpus to answer anything — see below.

## Environment variables

Keys stay server-side. The backend and the ingestion job hold every secret; the frontend
is a static bundle and receives exactly one variable, a URL.

**`backend/.env`** (`backend/.env.example`, `backend/config.py`):

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Supabase Postgres. On Render, use the Supavisor **session** pooler URI (port 5432) — the direct host is IPv6-only and the transaction pooler rejects psycopg3's prepared statements. |
| `SUPABASE_URL` | project URL, used to mint signed URLs for source PDFs |
| `SUPABASE_SERVICE_KEY` | service role key; reads the private corpus bucket |
| `OPENAI_API_KEY` | all model calls |
| `FRONTEND_ORIGIN` | the single origin CORS allows. Defaults to `http://localhost:5173`; set explicitly in production. |

**`ingestion/.env`** (`ingestion/.env.example`, `ingestion/config.py`): the same four
secrets as the backend, plus `CORPUS_BUCKET` (defaults to `corpus`). It must match the
bucket the upload script seeds and the bucket the backend reads.

**`frontend/.env`** (`frontend/.env.example`):

| Variable | Notes |
|---|---|
| `VITE_API_BASE_URL` | backend base URL, scheme included. Baked in at build time, so a change requires a rebuild. |

On Render every one of these is `sync: false` in `render.yaml` — set by hand in the
dashboard, never committed.

## Run ingestion

Three steps, in order, all from the repo root unless noted. Full detail in
[`ingestion/README.md`](ingestion/README.md).

1. **Migrate.** The schema belongs to the backend. From `backend/`:

   ```
   uv run python -m persistence.migrate
   ```

2. **Seed the bucket** from `DocumentCorpus/` (creates it private if absent, uploads with
   upsert). Credentials come from the environment or from `ingestion/.env`:

   ```
   uv run scripts/upload/upload_corpus.py
   ```

3. **Run the job.** From `ingestion/`:

   ```
   docker build -t medbrain-ingestion .
   docker run --rm --network host --env-file .env medbrain-ingestion
   ```

   `--network host` is required on Docker Desktop (Windows/macOS): Supabase's direct
   database host resolves to IPv6 only, which the default bridge network cannot reach.
   Without Docker: `uv sync --group extraction && uv run python -m pipeline`.

Re-running step 2 or step 3 is safe and cheap. The bucket upload is an upsert; the job
reconciles against the bucket, so a byte-identical document skips extraction entirely, a
revised one re-embeds only the chunks whose text changed, and a removed one has its
chunks deleted.

## Run evals

One command, from the repo root, with `backend/.env` filled in and the corpus already
ingested:

```
make eval
```

The target holds no logic — it runs `cd backend && uv run python -m eval`, which is the
equivalent if `make` is unavailable (it is not installed on Windows by default).

24 authored cases run through the real pipeline under two retrieval configurations —
`dense` (baseline) and `dense+sparse+rerank` — for the stretch goal's before/after. Traces
are saved to `backend/eval/runs/<stamp>.json`; the report prints to stdout and lands beside
the traces as `<stamp>.report.md`. Progress is a rewritable bar on stderr, so
`make eval > report.md` stays honest.

To re-score a saved run without touching the retrieval pipeline (the `gpt-5` judge still
runs), from `backend/`:

```
uv run python -m eval --score-only eval/runs/<stamp>.json
```

## Tests and CI

`.github/workflows/ci.yml` runs on push to `main` and on every pull request, as three
independent jobs. Each is reproducible locally:

| Job | Local equivalent | From |
|---|---|---|
| backend | `uv sync --frozen && uv run ruff check . && uv run mypy && uv run pytest` | `backend/` |
| ingestion | `uv sync --frozen && uv run ruff check . ../scripts/upload && uv run mypy && uv run mypy ../scripts/upload/upload_corpus.py && uv run pytest` | `ingestion/` |
| frontend | `npm ci && npm run lint && npm run typecheck && npm test && npm run build` | `frontend/` |

No job needs a database, an API key, or a network call. The ingestion job deliberately
syncs without `--group extraction`: nothing hermetic imports Unstructured or its CV
weights. The frontend build step is given `VITE_API_BASE_URL=http://ci.invalid`, since CI
only proves the bundle compiles.

## Repo layout

| Path | What |
|---|---|
| `backend/` | FastAPI app, retrieval pipeline, prompts, migrations, and the eval harness (`backend/eval/`) |
| `frontend/` | React + TypeScript + Vite chat UI |
| `ingestion/` | the containerized batch job: bucket → extract → carve → split → embed → reconcile |
| `scripts/upload/` | one-time seed of `DocumentCorpus/` into the private Storage bucket |
| `scripts/verification/` | a pointer only — the eval harness moved to `backend/eval/` |
| `DocumentCorpus/` | the 17 source PDFs |
| `render.yaml` | Render blueprint for the two deployed services |
| `DESIGN.md` | the design doc: architecture, rejected tradeoffs, failure analysis, debt |
| `AI_USAGE.md` | which AI tools were used, and where their output was overridden |
