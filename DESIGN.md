# DESIGN.md

**This is the source of truth for the MedBrain project design.** Current stack, feature
scope, architecture, and behavior all live here. `CLAUDE.md` points here rather than
duplicating any of it — if the two ever disagree, this file is right.

Living document: it describes the design **as it is now**, not the order it arrived in.
Edit it in place. Rewriting a section to match reality is correct and expected. The
append-only history of *why* each choice was made, and what was rejected, lives in
`DESIGN_RECORDS.md`.

> **Submission note:** the graded deliverable is 1–2 pages. This file will exceed that
> while it serves as the working source of truth. Trim it to the graded shape near the
> end — architectural decisions and rejected tradeoffs, eval failure analysis, next
> steps with another week, and known shortcuts — pulling the reasoning from
> `DESIGN_RECORDS.md`. Do not trim early; the working detail is worth more during the
> build than the page count is.

**Last updated:** 2026-08-12 15:04 -07:00

---

## What MedBrain is

A web app where a clinical operations professional — practice administrator, clinical
research coordinator, nurse educator — asks natural-language questions over a corpus of
15–30 public medical documents and gets **grounded, cited** answers.

It is a document-lookup tool for professionals. It is not a source of medical advice.

Built as a take-home assignment. The full spec is in
`take-home-assignment-fullstack-ai.md` — read it before making a scope decision.

## Stack

| Layer | Choice |
|---|---|
| Frontend | React, TypeScript, Tailwind — talks to the backend only through API endpoints. Vitest + Testing Library (jsdom) for its tests |
| Backend | Python, FastAPI, LangChain (`langchain-openai`) — owns all retrieval, reranking, and generation |
| Store | Supabase Postgres + `pgvector` — one store for chunks, embeddings, conversations, and app data. Schema ships as versioned SQL migrations applied by `python -m persistence.migrate` (psycopg) |
| Embeddings | OpenAI `text-embedding-3-large`, truncated to **1536 dims** via the API `dimensions` param — pgvector HNSW caps at 2000 dims, so native 3072 would force sequential scans |
| Keyword search | Postgres full-text (`tsvector` generated column, GIN index, `websearch_to_tsquery` + `ts_rank`) as the sparse half of hybrid — deliberately **not** BM25; see known debt |
| Generation LLM | OpenAI `gpt-5-mini`, streamed via `ChatOpenAI.astream` — cheap, sufficient for grounded extraction over the 8 provided chunks. Also runs the **advice gate** and **query rewriter** calls |
| Reranker LLM | OpenAI `gpt-5-nano` — scores 20 short passages as JSON; cheapest reliable scorer wins |
| Eval judge LLM | OpenAI `gpt-5` — deliberately stronger than the generator; runs per eval suite, not per query |
| Corpus files | Private **Supabase Storage bucket** is the source of truth; `DocumentCorpus/` in the repo is the seed copy, pushed up by a one-time local upload script. Backend mints short-lived (~5 min) signed URLs; file bytes never pass through the backend |
| PDF extraction | Unstructured `hi_res` (local CV layout models) — tables come out as structured HTML |
| Deploy | Render — backend (Docker web service) and frontend (static site), both declared in `render.yaml` at the repo root and deployed from the **`prod`** branch. The ingestion container runs **locally**, reading PDFs from the bucket and writing into hosted Supabase |
| Auth | None. The app is open and all conversation history is visible to everyone. |
| Repo | One repo: `frontend/`, `backend/` |

**Caching: none on the backend.** The frontend holds one sanctioned exception: an
in-memory `id → conversation` map in the store — no TTL, no eviction, no persistence — so
revisiting a conversation does not refetch it. It was taken for a correctness reason
rather than a performance one; see `DESIGN_RECORDS.md`. Nothing else caches anywhere, and
no further caching layer goes in without asking first. Ingestion idempotency
(`content_hash` unique constraint) is a spec requirement, not a cache, and stays.

**LangChain's scope is one rule with no exceptions: `langchain-openai`'s `ChatOpenAI` is
the model client for every LLM call** — generation, advice gate, query rewriter, reranker —
and its `OpenAIEmbeddings` is the embeddings client for both ingestion and query embedding.
Nothing else in LangChain is used, deliberately. Its retrievers and `PGVector` store are
declined because retrieval is hand-built SQL (HNSW + `ts_rank` + RRF) and `PGVector` keeps
metadata in a JSONB blob, which the typed-column schema rejected outright; its
`UnstructuredPDFLoader` is declined because ingestion needs the per-element `page_number`
and table HTML that the loader flattens away. The one component that earns its place
beyond the model clients is `RecursiveCharacterTextSplitter` for pass-2 chunking, which
ships in the separate `langchain-text-splitters` package. **The rule has a price:**
`langchain-openai` pins `openai<3`, so the direct `openai` dependency sits at 2.x rather
than 3.x. Accepted — once the gate and rewriter migrate, `openai` is imported only for its
exception type.

## The four answer behaviors

Each is graded separately and must actually work, not merely be requested in a prompt.

1. **Grounded** — answer only from retrieved context. Inline citations resolve to a
   specific document *and* section/page. Citations must be real, not decorative — so
   chunks carry their source location as metadata from ingestion onward.
2. **Honest** — when the corpus does not contain the answer, say so. This is tested
   deliberately and adversarially.
3. **Responsibly scoped** — two distinct pieces, both required: an **always-visible
   static disclaimer banner** in the UI ("document-lookup tool for professionals — not
   medical advice"), and a refusal path for personal medical advice ("should I stop
   taking my medication?") that returns a pre-written flag-response via the advice
   gate. This refusal is a **separate behavior** from "not in the corpus" and is scored
   separately.
4. **Streamed** — token streaming to the UI, with loading and error states that also
   handle a failure partway through a stream.

## Corpus

**17 FDA drug-label PDFs from DailyMed, all modern PLR format, all single-active** —
deliberately uniform. The corpus lives on the `plr-corpus` branch (commit `fa9b022`);
each document is programmatically verified PLR (HIGHLIGHTS OF PRESCRIBING INFORMATION
present, 15–17 numbered top-level sections). 10 drugs: amiodarone (1), apixaban (2),
bupropion (2), digoxin (2), escitalopram (2), mirtazapine (1), sertraline (1),
trazodone (1), venlafaxine (2), warfarin (3).

**Uniformity is a choice, not an accident:** old-format labels (no numbered sections),
OTC Drug Facts labels, and the ezetimibe+simvastatin multi-active combos were cut so
that one carving strategy and a single `drug_name` per document cover every case.
Dropped drugs (albuterol, aspirin, simvastatin) become clean *unanswerable* eval
questions — drugs a clinician would plausibly ask about that are genuinely out of
corpus.

**Quirks that remain, found by inspection, handled deliberately:**

- **Two heading-numbering variants:** most docs use `5 WARNINGS AND PRECAUTIONS`;
  Warfarin_2/3 use a trailing dot (`5.  WARNINGS`). Carving accepts the optional dot.
- **Case signals level:** top-level headings are ALL-CAPS; subsections are Title Case
  (`5.1 Hemorrhage`). The carving pattern handles both.
- **Every doc self-duplicates:** HIGHLIGHTS restates the label; page 2–3 is a bare
  table of contents. **Both are excluded from the index at ingestion.**
- **Same drug, multiple labelers:** 3 warfarins, 2 apixabans, etc. — near-identical
  regulatory prose that retrieval must discriminate between.
- **Packaging sections** (`PRINCIPAL DISPLAY PANEL`, `INGREDIENTS AND APPEARANCE`) with
  carton text and UNII code tables — **excluded from the index at ingestion.**

## Ingestion

A run-once, containerized batch job (run locally, never deployed): list the Storage
bucket and download each PDF → Unstructured `hi_res` extraction → clean page furniture →
stitch cross-page tables → **two-pass structure-aware chunking** → stamp metadata +
SHA-256 content hash → embed → reconcile into pgvector. Prerequisite: the one-time local
upload script seeds the bucket from `DocumentCorpus/` (storage only — it never writes
the registry).

**Exclusion list (applied at carving time):** the table-of-contents pages, the
`HIGHLIGHTS OF PRESCRIBING INFORMATION` block, and the packaging sections
(`PRINCIPAL DISPLAY PANEL` / `PACKAGE LABEL` variants, `INGREDIENTS AND APPEARANCE`)
are **not indexed**. TOC is content-free keyword bait; HIGHLIGHTS would make every key
fact exist twice and steal top-k slots from the authoritative sections it summarizes;
packaging text (carton copy, NDC barcodes, UNII tables) pollutes exact-token sparse
search. Accepted cost: inactive-ingredient questions become unanswerable — usable eval
material.

**Chunking:** Pass 1 carves the document into real sections from PLR numbered headers —
**one strategy, no per-class branching**, since the corpus is uniformly PLR. The heading
pattern accepts both observed variants (`5 WARNINGS` and `5.  WARNINGS` with trailing
dot) and both levels (ALL-CAPS top-level, Title Case subsections like `5.1 Hemorrhage`).
Pass 2 runs the recursive splitter *per section* (~1500 chars target), so sub-chunks
cannot cross a section boundary by construction. Section header text is repeated at the
top of each sub-chunk. Overlap exists only *within* a subdivided section, never between
sections. Tables are atomic blocks — serialized from `hi_res` HTML; oversized tables
split by row groups with the header row repeated. Images discarded. Nullable section
fields stay in the schema as cheap insurance: a chunk whose heading the pattern misses
degrades to a doc+page citation instead of failing the document (missing *pages*, by
contrast, fail loudly — see the citation floor).

**Idempotency — registry-driven reconciliation** (supersedes the earlier
`ON CONFLICT DO NOTHING` design): a `documents` registry table stores each document's
raw-file SHA-256 plus its storage object key (how citations resolve back to the source
file). Per run, reconciled **against the bucket**: new docs ingest, byte-identical docs skip entirely, changed
docs reconcile at chunk level (unchanged hashes kept, orphans deleted, new chunks
embedded), removed docs have their chunks deleted. Chunk changes + registry update
commit in one transaction per document. Chunk hash is content-only — the embedding
config is fixed; changing it means a full re-embed anyway.

## Retrieval — the one stretch goal

**Hybrid retrieval** is the chosen stretch goal, and only one is allowed. The reason is
domain-driven: this is medical software, so precise and accurate retrieval outranks
breadth of features even in a short demo. Dense vector search combines with keyword
search, then a rerank stage; reranking happens entirely in the backend.

Build retrieval as a **pluggable pipeline** — steps and tools swap in and out by
configuration. Two requirements follow from this:

- **Dense vector search always runs; everything else is an independent toggle** — sparse
  leg, reranker, gate, query rewriter, live judge — exposed as request parameters on the
  single query endpoint, covering the required before/after deltas. There is deliberately
  no retrieval *mode*: keyword-only search is not a configuration anyone would ship, and
  the graded delta is what the sparse leg and the reranker **add** to plain vector search.
- Retrieval config must be an explicit input, never ambient state, so the eval harness
  can run the same questions across configurations in one session.

**Candidate generation:** dense (pgvector HNSW, cosine `<=>`) and sparse
(`websearch_to_tsquery` + `ts_rank`) searches run over the same chunk table, each pulling
**top 40**. They run **sequentially, not concurrently** — one connection, and two round
trips are not the latency worth buying threads for at this corpus size. **Fusion is RRF**
(`k = 60`, sum of `1/(k+rank)`, agreement between lists compounds), taking **top 20** —
rank-based, so cosine and `ts_rank` score scales never need reconciling. With the sparse
toggle off, fusion becomes a passthrough — fusing one list against an empty one
reproduces that list's own order — so the dense-only configuration needs no separate code
path, and the reranker simply receives the dense candidates instead of the union.

**Reranker (toggleable):** a self-built **LLM reranker** — one batched pointwise call
scoring all 20 candidates 0–10 via `ChatOpenAI.with_structured_output`. **No temperature
is set** — the
gpt-5 family only accepts its default; determinism comes from the sort living in code,
not from the sampler. That sort is stable, so ties keep RRF order, and a response that
fails to score every candidate exactly once is discarded whole rather than partially
applied — the fused order stands. Numeric scores are kept for the eval trace. **Top 8**
go to generation. Chosen over a local cross-encoder (torch bulk would fatten the lean
backend container) and over a hosted rerank API (extra vendor).

**The built shape.** `retrieval/config.py` holds one frozen `RetrievalConfig` carrying
every switch (`gate`, `rewrite`, `sparse`, `rerank`) and every cut-off
(`candidate_limit=40`, `rrf_k=60`, `fused_limit=20`, `final_limit=8`). It is passed in,
never read from ambient state. `pipeline.run_retrieval()` is the single entry point —
gate → rewrite → embed → dense + sparse → fuse → rerank → cut — returning either a
`Refusal` or a `Retrieved` (the query actually searched, plus the chunks that survived).
Each survivor is a `ScoredChunk`: the `ChunkRow` plus its dense rank, sparse rank, RRF
score, and rerank score — that is what the eval trace reads and what generation cites
from. Each tool that needs a model owns that choice and exposes a factory —
`build_embeddings()` (`text-embedding-3-large` at 1536 dims) and `build_reranker()`
(`gpt-5-nano` bound to the score schema) — and the built clients are passed into
`run_retrieval` beside the raw `OpenAI` client the gate and rewriter still use. Injecting
them rather than constructing them inside the tools is what keeps the unit tests hermetic.
The tools (`embedder`, `dense_search`, `sparse_search`, `fusion`, `reranker`) know
nothing about the toggles or about each other; every composition decision lives in
`pipeline.py`. Both search legs select their columns from `ChunkRow.model_fields`, so a
query cannot drift from the model that validates its rows.

**Embedding config is fixed, not environment-tunable.** `EMBEDDING_MODEL` and
`EMBEDDING_DIMENSIONS` are constants in `backend/config.py`, imported by both retrieval
and ingestion — the single definition that keeps a stored vector and a query vector
comparable. Deliberately *not* `.env` values: the width is already frozen into the schema
as `vector(1536)`, so an env var would advertise a knob that cannot turn, and `.env`
files differing per machine is precisely the silent drift the single definition exists to
prevent.

**The gate and the rewriter run first — before anything is embedded or retrieved.**
They are two self-contained tools in `retrieval/tools/`, each with its own prompt,
response schema, and `gpt-5-mini` structured-output call on the raw query
(+ conversation history), composed by `retrieval/pipeline.py`'s `prepare_query()`:
gate first — a refusal stops the pipeline — then rewrite. The **advice gate**
(`advice_gate.py`): a single binary personal-medical-advice flag, nothing wider —
off-topic questions fall through to the honest not-in-corpus path. It **fails closed**:
if its call errors, the query is refused with a distinct "can't process right now"
message rather than answered ungated. The **query rewriter** (`query_rewriter.py`):
contextualizes the question into a standalone query using history and normalizes it
(brand → generic drug names, abbreviations expanded); the one rewritten string feeds
both retrieval legs. It **fails open**: a failed rewrite falls back to the raw query —
a broken rewriter never blocks a question. Each tool toggles independently as a request
parameter; with both off no LLM call runs and the raw query proceeds. In-app traffic
runs with both on — the toggles exist for eval deltas. A flagged question streams a
pre-written refusal with an empty sources mapping: no embedding, retrieval, or
generation. Both adapters still call the OpenAI SDK's structured-output parse directly;
moving them onto `ChatOpenAI.with_structured_output` to match the one-rule LangChain scope
is pending (see debt). The shared history-transcript rendering lives in
`retrieval/tools/history.py`. Prompt text and canned user-facing messages live
one-per-file in `backend/prompts/` and `backend/messages/`, re-exported through each
package's `__init__.py` index — the convention for every later prompt-bearing stage
(generation, reranker) and canned response.

## Storage schema and API surface

**Typed columns throughout — no JSON metadata blob on chunks.** Document identity lives
once on `documents`; chunks carry only per-chunk location. A citation is a join.

```sql
documents      id text PK (filename-derived) · storage_object_key · file_sha256
               · drug_name · manufacturer · formulation? · chunk_count · ingested_at

chunks         id bigserial PK · document_id FK (cascade) · content text
               · content_sha256 · embedding vector(1536) · tsv tsvector GENERATED
               · section_number text NULL · section_title text NULL
               · page_start int NOT NULL · page_end int NOT NULL
               · chunk_index int · chunk_type text ('text'|'table')
               UNIQUE (document_id, content_sha256)     -- reconciliation key
               HNSW(embedding) · GIN(tsv)

conversations  id uuid PK · title text · created_at
messages       id uuid PK · conversation_id FK · role ('user'|'assistant')
               · content text · sources jsonb NULL · created_at
```

**Schema management:** the DDL ships as ordered plain-SQL files in
`backend/persistence/migrations/` (`0001_initial_schema.sql`, …), applied in filename
order by `python -m persistence.migrate` — a small psycopg runner that records applied
filenames in a `schema_migrations` table, wraps each file plus its record row in one
transaction, and errors if an applied migration is missing from disk. No ORM, no vendor
migration tooling; `messages` also carries an index on `(conversation_id, created_at)`
for conversation loads.

**Schema↔type association:** one hand-written Pydantic row model per table
(`persistence/rows.py`), carrying only the columns the app reads (`chunks.embedding` and
`tsv` are deliberately absent — nothing reads them back). Adapters validate every row
into these models, so functions type-check against them via mypy and live drift surfaces
as a typed validation error at the boundary. `python -m healthcheck` verifies the
deployed schema against the models (column presence, type, nullability) via
`information_schema`.

**`messages.sources` freezes the tag→citation mapping** onto each assistant message at
stream `done`. History is shared and global; a reader who never saw the original SSE
`sources` event still gets working citations, and the snapshot stays honest even after
re-ingestion deletes or changes chunks. It is `jsonb` deliberately: a write-once
snapshot read whole, never filtered on — unlike chunk metadata, which is queried and
therefore typed.

**Endpoints:** `POST /conversations` · `GET /conversations` · `GET /conversations/{id}`
· `POST /conversations/{id}/query` (SSE; `?trace=true` returns one JSON payload) ·
`GET /documents/{id}/source-url` · `GET /health`.

**There is no DELETE and no PATCH, and that decides conversation lifecycle in the
client.** A conversation is created lazily, on its first question, and titled from that
question — the only moment a title can be set. Creating one on the "New chat" click
instead would litter a shared, global, unremovable list with empty rows.

**`trace=true` skips the history write.** The full pipeline runs — gate, retrieval,
fusion, rerank, generation — but nothing lands in `conversations`/`messages`. The eval
harness fires ~100+ requests per full run; without the skip they would bury the shared
UI in robot conversations with no cleanup path. Persistence logic is covered by a unit
test instead.

## Citations and streaming

Chunk metadata (drug, document, formulation, manufacturer, section number + title, chunk
index, content hash, text/table flag) is the chunk's permanent identity and the real
citation. At context-assembly time each retrieved chunk gets a per-query sentinel tag
(`[[S1]]`, `[[S2]]`); the model emits only tags inline. **The tag→citation mapping is
sent to the client as the first SSE event, before any tokens**, so citation resolution
is client-side rendering — the backend never rewrites a stream. Event order: `sources` →
`token`(s, sentinels passed through raw; client buffers split sentinels) → `done` (carries
post-hoc annotations) / `error`. Gating decides what streams before tokens flow. Trace
mode returns one JSON payload (answer + full retrieval trace + scores) instead of a
stream — that is what the eval harness consumes.

**The built shape.** `backend/chat/` splits four ways. `context.py` is pure: it assigns
positional tags (`S1`, `S2`, …), builds the tag→citation mapping, renders the tagged
excerpts the prompt carries, and extracts the tags an answer actually emitted (the input
to the eval's grounding check). `events.py` defines the four event payloads and their SSE
encoding — payloads are JSON, so a newline inside answer text cannot split a frame.
`generation.py` is the adapter: it owns the model choice and yields `ChatOpenAI.astream`
deltas. `answer.py` composes them into `stream_answer_events()`, which the SSE endpoint
serves, and `trace_answer()`, which collects the **same** event stream into one payload —
so the eval harness measures the path users actually get instead of a parallel one.

**Its input is `RetrievedChunk`: a `ChunkRow` plus the document it belongs to**, where the
document is reached through a `CitedDocument` `Protocol` declaring only `id` and
`drug_name`. `DocumentRow` satisfies it structurally, so no field is re-declared and a
rename in the row model fails the type check rather than drifting; inside `chat/`, reading
any other document field is a mypy error. Retrieval returns `ScoredChunk` (a `ChunkRow`
plus its scores) and does not carry the document, so joining chunk to document is the
query endpoint's job.

**A citation is `document_id` + `drug` + `section_number` + `section_title` +
`page_start`.** Section fields go null on a chunk with no carved section; `page_start` is
the guaranteed floor. Deliberately *not* carried: `manufacturer` and `formulation`. Six of
the ten drugs have multiple labels, so `warfarin § 5.1` is ambiguous between three
documents on its face — accepted, because `document_id` is in the payload and resolves
click-through correctly. Revisit if the ambiguity reads badly in the UI.

**Two paths never reach the model.** A gate refusal (decided upstream in retrieval) and an
empty chunk list both stream through the same canned-response helper — `sources` with an
empty mapping, one `token` carrying the pre-written text, then `done` — so a canned answer
reaches the client through exactly the contract a generated one does. The empty-chunk case
is also where the pre-announced relevance threshold lands: filtering to zero produces the
decline path with no extra branch and no generation spend.

**A failure partway through a stream ends in `error`, not `done`.** The client has already
rendered part of an answer, so a dropped generation call emits an `error` event carrying a
canned message rather than truncating silently — the mid-stream case the assignment names.

**The generation prompt sees the standalone question and the excerpts only — never the
conversation history.** Making a follow-up standalone is the query rewriter's job, and
keeping history out of the context window means no ungrounded prior turn competes with the
labeling for the model's attention. Cost, accepted: with `rewrite` toggled off a follow-up
loses its referent, which is exactly the delta that toggle exists to measure.

**Document + page is the guaranteed floor of every citation — never a fallback.** Every
chunk carries **`page_start`/`page_end` (`NOT NULL`)** captured at ingestion
(Unstructured elements carry `page_number`; a stitched cross-page table spans pages,
deep link uses `page_start`). A chunk whose pages cannot be resolved is an ingestion
**error that fails loudly**, not a chunk with a weaker citation. Only the *section* tier
degrades: document + section + page when the chunk has a carved section, document + page
when it doesn't (on the uniform PLR corpus this is a rare insurance case, not an
expected class of documents). Section fields are nullable by design; page fields are
not. Every served chunk deep-links to its page.

**Click-through with page deep-linking:** a citation renders as drug + section; clicking
it calls `GET /documents/{id}/source-url`, which mints a ~5-minute signed URL against
the private bucket (object key from the `documents` registry). The client appends
`#page=N` from the chunk's `page_start` — the fragment stays client-side, so it cannot
break the URL signature — and the PDF opens in a new tab straight from Supabase Storage,
landing on the cited page in browsers whose PDF viewer honors `#page=` (Chromium,
Firefox; Safari degrades to page 1). The backend never proxies file bytes.

**The client shape.** `api/http.ts` is the shared boundary — URL building, `ApiError`,
JSON requests; `api/client.ts` holds the four non-streaming calls; `api/stream.ts` reads
the SSE body by hand, because `EventSource` only issues GET and the query endpoint is a
POST. Frame splitting (`lib/sse.ts`), sentinel buffering (`lib/sentinels.ts`) and title
derivation (`lib/title.ts`) are pure functions with no network, unit-tested directly.
Responses are **cast, not validated**: there is no runtime schema layer, so a backend
rename surfaces as a broken render rather than a typed error (see debt).
`state/ConversationStore.tsx` owns the cache *and* the streams — a stream writes into the
store, never into component state, because a message is persisted server-side only at
`done`, so an unmounting component would otherwise destroy text that exists nowhere else.
The composer is disabled while its conversation streams, which makes one-stream-per-
conversation true by construction instead of by reconciliation.

**A stream that ends without `done` or `error` is an interruption.** At the byte level a
dropped connection is indistinguishable from a clean finish — the reader simply ends — so
the client tracks whether a terminal event arrived and treats its absence as failure. The
partial answer is kept on screen and labeled incomplete rather than discarded: it got as
far as it got, and hiding that is less honest than showing it. Half-arrived sentinels are
withheld while streaming, so `[[S` never flashes as literal text before its brackets
land.

## Eval harness

Its own project feature and the heaviest-weighted piece of engineering. Requirements:
≥15 authored question/expected-answer pairs, including ≥3 unanswerable from the corpus,
≥2 requiring synthesis across multiple documents, and ≥2 personal-medical-advice
questions the app must decline. It scores **both** retrieval quality (hit rate / MRR
against expected sources) and answer quality, runs from a single command, and prints a
report. If time runs short, cut a UI feature — never the eval harness.

Shape: ~15–20 hand-authored prompts, each labeled with expected documents + sections and
an expected answer (refusal text for unanswerables). The harness drives the **real
backend** through the query endpoint's trace mode, varying one pipeline toggle at a time
— dense alone, dense + sparse, and each of those with the reranker on. Metrics:
Recall@K, MRR, Precision@K at
document and section granularity; behavioral checks for look-alike discrimination
(sertraline vs escitalopram, warfarin vs apixaban), unanswerable behavior, and a
grounding check that every emitted citation tag resolves to an actually-retrieved chunk.
Answer quality is scored by an **eval-side LLM judge inside the harness** — automated
and mandatory (distinct from the optional live-pipeline judge, which only annotates).

## Testing and CI

The codebase separates **pure logic from I/O adapters** so logic is testable without
services: every feature splits into typed functions (inputs → outputs, no network) and
thin adapters that talk to OpenAI / Supabase / Storage. External I/O is validated at the
adapter boundary with typed models; data that doesn't match the expected shape becomes a
graceful, typed error surfaced through the API's error states — never a raw stack trace
to the user.

Two test layers, deliberately separate:

- **Unit tests (hermetic, run in CI):** pytest against the pure logic with typed
  fixtures — section carving (both numbering variants, both heading cases), splitter
  boundary honoring, RRF fusion math, reranker JSON-fallback parsing, tag→citation
  assembly and section degradation, SSE event order and encoding, the no-context and
  mid-stream-failure paths, reconciliation diffing. No API keys, no network. A handful of
  meaningful tests, not coverage-chasing. Async paths are driven with `asyncio.run` from
  synchronous tests rather than adding `pytest-asyncio`.
- **Frontend tests (hermetic, run in CI):** Vitest against the pure logic — SSE frame
  splitting across network chunk boundaries, sentinel buffering, title derivation — plus
  a few integration tests that render the real components against a stubbed `fetch`
  returning a real `ReadableStream`. One drives the whole wired path: ask a question,
  stream tokens into the DOM, resolve a citation to a signed URL with its `#page=`
  fragment, and cut the stream without a terminal event to assert the incomplete state.
  There is deliberately **no dev-time mock backend** — the mock is a test fixture, not a
  fake server, so the real fetch and SSE parser are what the tests exercise.
- **Health checks (live, not in CI):** a small separately-run suite
  (`python -m healthcheck`) that verifies real connections — DB reachable and the live
  schema matching the row models (built); bucket listable, OpenAI key valid (still to
  come). Used locally and as a post-deploy smoke test.

**CI (GitHub Actions, on pull requests + pushes to `main`):** backend — ruff, mypy,
pytest (hermetic only); frontend — eslint, tsc, vitest, build. Both jobs run
unconditionally on every PR (no path filtering). No secrets in CI.

## Deployment

**`render.yaml` at the repo root declares both services**, applied as a Render Blueprint
from the **`prod`** branch — a long-lived deploy branch fast-forwarded from `main`, so
what is live is always a commit that passed CI. `ingestion/` is deliberately absent from
the blueprint: it is a run-once local batch job.

**Backend — Docker web service**, `rootDir: backend`, health check `/health`. The
container binds `$PORT`, which Render injects, so the `CMD` is shell form with an
`exec` prefix: shell form because the exec form would pass uvicorn the literal string
`$PORT`, and `exec` so uvicorn is PID 1 and receives the `SIGTERM` Render sends to drain
a deploy — without it a redeploy would wait out the kill timeout on every ship. Uvicorn
is called directly off the synced venv (`ENV PATH=/app/.venv/bin:$PATH`) rather than
through `uv run`, which would otherwise sit between the container and its own process.

**`DATABASE_URL` must be the Supavisor *session* pooler URI (port 5432)** — not
Supabase's direct connection, whose host is IPv6-only while Render has no IPv6 egress,
and not the transaction pooler on 6543, which rejects the prepared statements psycopg3
issues once a query repeats. This is the one env value whose *form* is load-bearing.

**Frontend — static site**, `npm ci && npm run build`, published from `dist`. No SPA
rewrite rule: the app is a single route with no client-side router.

**The two services reference each other's URLs, and neither can be filled in by the
blueprint.** The backend's `FRONTEND_ORIGIN` is the single origin CORS allows; the
frontend's `VITE_API_BASE_URL` is baked into the bundle at build time. Render's
`fromService` yields a bare hostname with no scheme, so both are declared `sync: false`
and set once in the dashboard after the first apply — and the frontend needs an explicit
redeploy after its value lands, because changing a build-time variable does not change an
already-built bundle.

**A missing `VITE_API_BASE_URL` fails the build rather than shipping.** `vite.config.ts`
throws on a production build when the variable is unset; previously the build went green
and produced a bundle requesting `undefined/conversations`, a failure visible only in the
browser. CI passes a placeholder URL, since CI only proves the bundle compiles.

**Free tier, accepted:** the backend instance spins down after inactivity, so the first
request after an idle period pays a cold start before any token streams.

## Failure analysis

_Not yet written — fill in from eval runs. Source material accumulates in_
`DESIGN_RECORDS.md`.

## What another week would buy

_Not yet written. Must cover scaling to 10,000 documents, multi-tenancy, cost controls,
and latency budgets._

Known scaling limits already identified:

- `pgvector` plus Postgres full-text ranking is right at 15–30 documents and is not
  automatically right at 10,000. At scale, the keyword leg's production answer is a real
  BM25 index in or beside the database, not `ts_rank`.
- Shared global conversation history has no tenancy boundary. Multi-tenancy means
  row-level tenancy on the conversation tables plus per-tenant corpus isolation.

## Known shortcuts and technical debt

- No caching anywhere, deliberately. See `DESIGN_RECORDS.md` for the five rejected caches.
- No auth; conversation history is global and shared.
- The sparse leg is `ts_rank`, which is **not** BM25 — it lacks BM25's document-length
  normalization and term saturation. The planned `rank_bm25` comparison was dropped on
  scope; the graded eval delta is hybrid-vs-dense, not ts_rank-vs-BM25. Never describe
  the sparse leg as "BM25".
- The advice gate and query rewriter still call the OpenAI SDK directly, so the "every
  LLM call goes through `ChatOpenAI`" rule is true of generation and not yet of them.
  Retrofit is two `with_structured_output` swaps plus an `isinstance` narrow at each
  tool's existing failure branch; it was left out of the generation branch to avoid
  colliding with the retrieval session working in those files.
- The live LLM-as-judge is not built. `DoneEvent.judge_grounded` is the typed slot it
  would fill and currently always serializes as `null`.
- **The frontend casts API responses instead of validating them.** There is no runtime
  schema layer, so the backend row models are enforced on their side of the wire and
  nowhere on this one. A renamed field becomes `undefined` inside a component rather than
  a typed error at the boundary — the opposite of the backend's stated adapter discipline,
  accepted because the corpus of callers is small and the cost of a schema library was
  judged not worth it for a demo.
- **The frontend has no mock backend outside tests.** `npm run dev` renders a UI wired to
  a backend that must actually exist. The first real HTTP request the client ever makes
  will be on cutover day.
- **The backend mounts no CORS middleware.** `api/app.py` adds none, so a browser calling
  it cross-origin will be blocked. Either middleware or a Vite dev proxy has to land
  before the frontend talks to a real backend.
- The assistant messages the client renders after a stream are built locally rather than
  re-fetched, so a conversation's cached view is the client's reconstruction until the
  next full load. It matches what the backend persisted at `done`; it is not read back to
  prove it.

## Two things to design for now, without building them

- **A relevance threshold below which the app declines to answer.** The assignment
  pre-announces this as a live modification in the follow-up interview. The drop-in spot
  exists and is marked: `retrieve_chunks()` in `retrieval/pipeline.py`, between the rerank
  step and the final cut, where `ranked` would be filtered on `rerank_score` (or on
  `rrf_score` with the reranker off) and an empty result becomes the decline path. The
  threshold itself is deliberately not implemented.
- **Every significant line must be defensible out loud.** Prefer the version that can be
  explained over the version that is clever.

## Other graded surface

A README covering local setup, ingestion, and evals; CI on push; and the **commit history
itself** — a coherent sequence of commits, not one large dump.
