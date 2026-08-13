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

**Last updated:** 2026-08-12 20:24 -07:00

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
| Generation LLM | OpenAI `gpt-5-mini`, streamed via `ChatOpenAI.astream` — cheap, sufficient for grounded extraction over the 5 provided chunks. Also runs the **query gate** and **query rewriter** calls |
| Reranker LLM | OpenAI `gpt-5-nano` — scores 20 short passages as JSON; cheapest reliable scorer wins |
| Eval judge LLM | OpenAI `gpt-5` — deliberately stronger than the generator; runs per eval suite, not per query |
| Corpus files | Private **Supabase Storage bucket** is the source of truth; `DocumentCorpus/` in the repo is the seed copy, pushed up by a one-time local upload script. Backend mints short-lived (~5 min) signed URLs; file bytes never pass through the backend |
| PDF extraction | Unstructured `hi_res` (local CV layout models) — tables come out as structured HTML |
| Deploy | Render — backend and frontend. The ingestion container runs **locally**, reading PDFs from the bucket and writing into hosted Supabase |
| Auth | None. The app is open and all conversation history is visible to everyone. |
| Repo | One repo, three projects plus scripts: `frontend/`, `backend/`, `ingestion/` (run-locally batch job, not deployed), `scripts/` |

**Caching: none on the backend.** The frontend holds one sanctioned exception: an
in-memory `id → conversation` map in the store — no TTL, no eviction, no persistence — so
revisiting a conversation does not refetch it. It was taken for a correctness reason
rather than a performance one; see `DESIGN_RECORDS.md`. Nothing else caches anywhere, and
no further caching layer goes in without asking first. Ingestion idempotency
(`content_hash` unique constraint) is a spec requirement, not a cache, and stays.

**LangChain's scope is one rule with no exceptions: `langchain-openai`'s `ChatOpenAI` is
the model client for every LLM call** — generation, query gate, query rewriter, reranker —
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

- **Two heading-numbering variants, mixed *within* a document:** most headings read
  `5 WARNINGS AND PRECAUTIONS`; some take a trailing dot (`5.  WARNINGS`). Warfarin_2
  uses both on one page, so the optional dot is a per-heading rule, not a per-document
  one.
- **Case does not signal level** (corrected by inspection, 2026-08-12): `8.1  PREGNANCY`
  is an ALL-CAPS *subsection* in Warfarin_2. Level comes from the number's shape
  (`5` vs `5.1`); case is ignored entirely.
- **Unnumbered sections are real content:** every document's boxed warning
  (`WARNING: BLEEDING RISK`, `WARNING: SUICIDAL THOUGHTS AND BEHAVIORS`) carries no
  number, and several carry a `MEDICATION GUIDE` after section 17. This is what
  nullable `section_number` is actually for.
- **Carton text mimics numbered headings:** `1 mg:`, `10 mg White (dye`, `30 Tablets`
  all match a naive pattern — 27 false hits in Warfarin.pdf alone. Carving also
  requires a title-shaped remainder and a section number within 1–17.
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

**It is its own top-level project — `ingestion/`, beside `backend/` and `frontend/`,
with its own `pyproject.toml`, lockfile, Dockerfile, and tests.** No API path reaches
it and the backend never imports it; they meet only at Supabase. The separation is
also what keeps the deployed backend lean: `unstructured[pdf]` and its CV weights sit
in a non-default dependency group that only the ingestion image installs, so the
backend image and CI cannot pull them in by accident. The schema stays owned by
`backend/persistence/migrations/` — ingestion assumes the tables exist and writes rows
into them, so there is exactly one DDL and one live-schema verifier.

**Document identity** (`drug_name`, `manufacturer`, `formulation`) comes from one
`gpt-5-mini` structured-output call per new or changed document, over the label's
opening and closing text — where the product title and the "Manufactured by" statement
live. It runs at ingestion, never per query. It **fails loudly**: a document whose
identity cannot be read is not registered under a guess, because those fields are what
a citation shows. `drug_name` is the lowercase generic — the string a citation renders.

Both of ingestion's OpenAI calls obey the one-rule LangChain scope: identity is
`ChatOpenAI.with_structured_output(DocumentIdentity)` with the result narrowed by
`isinstance`, and chunk embedding is `OpenAIEmbeddings`, the same client the query side
uses. `openai` is imported here only for `OpenAIError`. Ingestion calls Unstructured's
`partition_pdf` directly rather than through `UnstructuredPDFLoader`, for the
per-element `page_number` and table HTML the loader flattens away.

**Exclusion list (applied at carving time):** the table-of-contents pages, the
`HIGHLIGHTS OF PRESCRIBING INFORMATION` block, and the packaging sections
(`PRINCIPAL DISPLAY PANEL` / `PACKAGE LABEL` variants, `INGREDIENTS AND APPEARANCE`)
are **not indexed**. TOC is content-free keyword bait; HIGHLIGHTS would make every key
fact exist twice and steal top-k slots from the authoritative sections it summarizes;
packaging text (carton copy, NDC barcodes, UNII tables) pollutes exact-token sparse
search. Accepted cost: inactive-ingredient questions become unanswerable — usable eval
material.

**The exclusion list is implemented as a body window**, not as a per-section blocklist:
the body opens after the last element whose text is exactly
`FULL PRESCRIBING INFORMATION` (which drops HIGHLIGHTS and the TOC in one rule, since
the contents page is headed `FULL PRESCRIBING INFORMATION: CONTENTS`) and closes at the
first packaging heading. Both boundaries were verified present and correctly ordered in
all 17 documents; packaging is terminal in every one, Warfarin.pdf included, where
eleven display panels and the product-data tables run to the last page. Content before
the first heading inside the window is TOC residue and is dropped — four documents leak
the "Sections or subsections omitted…" footnote there.

**Chunking:** Pass 1 carves the document into real sections from PLR numbered headers —
**one strategy, no per-class branching**, since the corpus is uniformly PLR. A heading
is a number of 1–17 with an optional trailing dot and an optional `.n` subsection, plus
a title-shaped remainder; level comes from the number's shape, not from case. Carving
splits at the **finest** heading, so `5.1 Hemorrhage` is its own section rather than
part of a 20-page section 5, and a parent that holds only subsections yields no chunk
of its own. Unnumbered structural headings (boxed warnings, `MEDICATION GUIDE`) carve
sections with a null number.
Pass 2 runs the recursive splitter *per section* (~1500 chars target, minus the space
the repeated heading takes), so sub-chunks cannot cross a section boundary by
construction. Section header text is repeated at the top of each sub-chunk. Overlap
exists only *within* a subdivided section, never between sections. Tables are atomic
blocks — serialized from `hi_res` HTML; oversized tables split by row groups with the
header row repeated. Images discarded. Nullable section
fields stay in the schema as cheap insurance: a chunk whose heading the pattern misses
degrades to a doc+page citation instead of failing the document (missing *pages*, by
contrast, fail loudly — see the citation floor).

**Pages are resolved, not guessed.** Each element contributes a segment to its
section's joined text; a chunk's page span is read from the segments its character
range covers, using the offsets the splitter itself reports. A chunk whose range maps
to no segment raises. Cross-page tables are stitched into one element that spans both
pages, so a stitched table cites `page_start` and still records where it ends.

**Idempotency — registry-driven reconciliation** (supersedes the earlier
`ON CONFLICT DO NOTHING` design): a `documents` registry table stores each document's
raw-file SHA-256 plus its storage object key (how citations resolve back to the source
file). Per run, reconciled **against the bucket**: new docs ingest, byte-identical docs skip entirely, changed
docs reconcile at chunk level (unchanged hashes kept, orphans deleted, new chunks
embedded), removed docs have their chunks deleted. Chunk changes + registry update
commit in one transaction per document — the connection is opened `autocommit=True` so
each `connection.transaction()` block is a real per-document BEGIN/COMMIT rather than a
savepoint inside one run-long transaction, and with TCP keepalives so the pooler cannot
idle-kill the socket while a document spends minutes in extraction. Ingestion's
`DATABASE_URL` points at Supabase's IPv4 session pooler, not the direct DB host — the
direct host is IPv6-only and unreachable from Docker here. Chunk hash is content-only — the embedding
config is fixed; changing it means a full re-embed anyway.

**A kept chunk that moved is relocated, not re-embedded.** Because the hash covers
content alone, a revised label can leave a chunk's text identical while its page or
index changes — and the page is what the citation deep-links to. The chunk diff
therefore has four outcomes, not three: insert, delete, *relocate* (update
`page_start`/`page_end`/`chunk_index`/section in place, embedding untouched), and
unchanged. Content that repeats inside one document collapses to a single chunk;
`UNIQUE (document_id, content_sha256)` means the second copy would be the same row.

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
**top 10**. The sparse leg **OR-s its lexemes**: `websearch_to_tsquery` joins bare terms
with `&`, which demands a chunk holding every word of the question and so returned nothing
at all for 18 of 18 eval questions. The operators are rewritten to `|` textually, which
keeps phrase and negation operators intact and lets `ts_rank` do the ordering. They run **sequentially, not concurrently** — one connection, and two round
trips are not the latency worth buying threads for at this corpus size. **Fusion is RRF**
(`k = 10`, sum of `1/(k+rank)`, agreement between lists compounds), taking **top 20** —
rank-based, so cosine and `ts_rank` score scales never need reconciling. **`k` is sized to
the candidate list, not inherited.** The published default of 60 was tuned for TREC runs
about 1000 deep, where it still spreads scores 17-fold; over 10 candidates it spreads them
11% and rank stops meaning anything, leaving agreement between the legs as the only signal
that moves a chunk. At `k = 10` a rank-1 hit scores 0.091 against a rank-10 hit's 0.050 —
position separates again, while a chunk both legs found still outranks one only dense saw. With the sparse
toggle off, fusion becomes a passthrough — fusing one list against an empty one
reproduces that list's own order — so the dense-only configuration needs no separate code
path, and the reranker simply receives the dense candidates instead of the union.

**Reranker (toggleable):** a self-built **LLM reranker** — one batched pointwise call
scoring every fused candidate 0–10 via `ChatOpenAI.with_structured_output`. **No temperature
is set** — the
gpt-5 family only accepts its default; determinism comes from the sort living in code,
not from the sampler. That sort is stable, so ties keep RRF order, and a response that
fails to score every candidate exactly once is discarded whole rather than partially
applied — the fused order stands. Numeric scores are kept for the eval trace.

**Relevance threshold: `rerank_score >= 3`.** Candidates the reranker scored below 3 are
dropped before the final cut, and **filtering to zero is the decline path** — the caller
streams the not-in-corpus message and never makes the generation call, reusing the
existing empty-chunk branch with no new code. An *unscored* chunk passes: `rerank_score`
is None both when the reranker is off and when its call failed open, and neither is a
judgement against the chunk, so a single bad OpenAI call cannot black out every query.
The 3 was read off the score distribution of a real run, not guessed — see
`DESIGN_RECORDS.md`. Then **top 5** go to generation. Chosen over a local cross-encoder (torch bulk would fatten the lean
backend container) and over a hosted rerank API (extra vendor).

**The built shape.** `retrieval/config.py` holds one frozen `RetrievalConfig` carrying
every switch (`gate`, `rewrite`, `sparse`, `rerank`) and every cut-off
(`candidate_limit=10`, `rrf_k=10`, `fused_limit=20`, `final_limit=5`,
`min_rerank_score=3`). It is passed in,
never read from ambient state. `pipeline.run_retrieval()` is the single entry point —
gate → rewrite → embed → dense + sparse → fuse → rerank → filter → cut — returning either a
`Refusal` or a `Retrieved` (the query actually searched, plus the chunks that survived).
Each survivor is a `ScoredChunk`: the `ChunkRow` plus its dense rank, sparse rank, RRF
score, and rerank score — that is what the eval trace reads and what generation cites
from. Each tool that needs a model owns that choice and exposes a factory —
`build_embeddings()` (`text-embedding-3-large` at 1536 dims) and `build_reranker()`
(`gpt-5-nano` bound to the score schema) — and the built clients are passed into
`run_retrieval` beside the raw `OpenAI` client the gate and rewriter still use. Injecting
them rather than constructing them inside the tools is what keeps the unit tests hermetic.
The tools know nothing about the toggles or about each other; every composition decision
lives in `pipeline.py`. Both search legs select their columns from
`ChunkRow.model_fields`, so a query cannot drift from the model that validates its rows.

**Package layout — the folders are the pipeline stages.** `retrieval/` holds `config.py`
(the switches), `contract.py` (the vocabulary callers speak — `HistoryMessage`,
`ScoredChunk`, `Refusal`, `Retrieved`), `pipeline.py` (composition only), and three stage
packages: **`query/`** (query gate, query rewriter, and the transcript rendering they
share) → **`search/`** (embeddings client, dense leg, sparse leg, and the chunk columns
plus row reader they share) → **`ranking/`** (RRF fusion, LLM reranker). Callers import
`retrieval.contract` and `retrieval.pipeline`; the stage packages are internal. Each
stage's shared helper lives inside that stage, so no module sits in a folder it does not
belong to. `tests/retrieval/` mirrors the layout.

**Embedding config is fixed, not environment-tunable.** `EMBEDDING_MODEL` and
`EMBEDDING_DIMENSIONS` are constants in `backend/config.py`, imported by both retrieval
and ingestion — the single definition that keeps a stored vector and a query vector
comparable. Deliberately *not* `.env` values: the width is already frozen into the schema
as `vector(1536)`, so an env var would advertise a knob that cannot turn, and `.env`
files differing per machine is precisely the silent drift the single definition exists to
prevent.

**The gate and the rewriter run first — before anything is embedded or retrieved.**
They are two self-contained tools in `retrieval/query/`, each with its own prompt,
response schema, and `gpt-5-mini` structured-output call on the raw query
(+ conversation history), composed by `retrieval/pipeline.py`'s `prepare_query()`:
gate first — a refusal stops the pipeline — then rewrite. The **query gate**
(`query_gate.py`): one call returning one reason — `personal_advice`, `unsafe`,
`off_topic`, or `none` — and each refusing reason has its own pre-written message, so a
harm-seeking question is not told it asked for personal medical advice. `unsafe` is
harm-*seeking*, not dangerous-*sounding*: describing a label's overdose or toxicity
section is the tool's job and passes. `off_topic` means outside medicine entirely
(spiders, the weather); a question about a drug the corpus may not hold is on topic and
falls through to the honest not-in-corpus path. It **fails closed**: if its call errors,
the query is refused with a distinct "can't process right now" message rather than
answered ungated. The **query rewriter** (`query_rewriter.py`):
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
`retrieval/query/transcript.py`. Prompt text and canned user-facing messages live
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

**The built API shape.** `api/` is routing and transport only: `app.py` (factory:
lifespan plus one `psycopg.Error → 503` handler), `dependencies.py` (a psycopg
connection per request — deliberately no pool at demo scale, Supabase's pooler absorbs
the churn — plus the typed accessor holding the single `cast` off `app.state`),
`models.py` (request bodies, the four pipeline toggles mapping onto `RetrievalConfig`,
and the trace payload — row models serialize directly as responses), `sse.py` (the
wire framing, and the only module that knows the transport is SSE), and `routes.py`
(handlers that call `prepare_turn` and nothing deeper). `clients.py` at the backend
root is the composition root — every shared client built once at startup from explicit
settings: generation `ChatOpenAI`, embeddings, reranker, the raw `OpenAI` the
gate/rewriter still use, and the Supabase storage client. It sits outside `api/`
because the eval harness builds the same clients with no app around them.

Non-streaming handlers are plain `def`, so FastAPI's threadpool absorbs their blocking
I/O; only the query endpoint is async, and its blocking prefix is a single
`run_in_threadpool(prepare_turn, …)`. SSE is hand-rolled — `StreamingResponse` over
`encode_sse` frames; `sse-starlette` was rejected because it would make the tested
encoder dead code. The `build_embeddings(api_key)` / `build_reranker(api_key)`
factories take the credential explicitly (the `.env`-not-in-`os.environ` trap is
closed; nothing reads ambient env). `CORPUS_BUCKET = "corpus"` and the 300 s
signed-URL TTL are fixed constants in `config.py`; the upload script must seed that
bucket name.

**`conversation/` composes one question end to end**, and is the only module that
knows `retrieval/`, `chat/`, and `persistence/` all exist. `turn.py` holds
`prepare_turn()`: retrieval, then the chunk→document join, then the answer stream,
returning a `Turn` (the searched query, whether it was refused, the scored chunks,
the joined chunks, and the events). It is **the one place a refusal is told apart from
a retrieved result** — a refusal is simply a turn with no query, no chunks, and the
canned stream — so the SSE endpoint, the trace endpoint, and the eval harness all read
the same fields and none of them branches. `history.py` adapts between stored messages
and the two packages' own shapes (`MessageRow` → `HistoryMessage`; the citation mapping
→ its `jsonb` snapshot). `persist.py` is a pass-through wrapper, so persistence is
something a caller *adds to a stream* rather than a step inside it: the SSE endpoint
wraps, the trace endpoint and the harness do not. History writes: the user message
lands before the stream starts, the assistant message at `done` with the frozen sources
snapshot, written before that event is yielded so a failed write cannot follow a
success signal; a refusal persists with an empty snapshot through that same path, with
no special case; an errored stream never reaches `done` and persists nothing.

**CORS:** `create_app()` wires Starlette's `CORSMiddleware` allowing one origin from
`Settings.frontend_origin` (`FRONTEND_ORIGIN` env var, default `http://localhost:5173`
for the Vite dev server). The deployed frontend origin is set via that env var on the
backend host.

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
(`[[S1]]`, `[[S2]]`); the model emits only tags inline. **The sentinel is written
strictly and read leniently** — the prompt and `sentinel()` use `[[S1]]`, but both readers
(`chat/context.py`, `lib/sentinels.ts`) also accept `[S1]`, because the model drifts to one
bracket on longer answers and a strict reader turns that into dead literal text where a
citation belongs. **The tag→citation mapping is
sent to the client as the first SSE event, before any tokens**, so citation resolution
is client-side rendering — the backend never rewrites a stream. Event order: `sources` →
`token`(s, sentinels passed through raw; client buffers split sentinels) → `done` (carries
post-hoc annotations) / `error`. Gating decides what streams before tokens flow. The eval
harness consumes the same events in-process, collected into one payload by
`collect_answer()` — it does not go over HTTP (see Eval harness).

**The built shape.** `backend/chat/` is a self-contained generation package that knows
nothing about conversations, history, or transports. `contract.py` is the vocabulary
callers speak — `RetrievedChunk` going in, the four event payloads and `Citation` coming
out, and the `CollectedAnswer` a finished stream folds into; nothing outside the package
imports anything deeper. `join.py` pairs retrieved chunks with their parent documents
(one query, then a pure pairing). `context.py` is pure: it assigns positional tags
(`S1`, `S2`, …), builds the tag→citation mapping, renders the tagged excerpts the prompt
carries, and extracts the tags an answer actually emitted (the input to the eval's
grounding check). `generation.py` is the adapter: it owns the model choice and yields
`ChatOpenAI.astream` deltas. `stream.py` produces the events. `collect.py` folds them
back, and is **written once and used twice** — the history write freezes the fold onto
the assistant message and the eval harness scores it, and the two must not disagree. How
an event reaches a client is not this package's business: the SSE framing lives in
`api/sse.py`, so payloads are JSON and a newline inside answer text cannot split a frame.

**Its input is `RetrievedChunk`: a `ChunkRow` plus the document it belongs to**, where the
document is reached through a `CitedDocument` `Protocol` declaring only `id` and
`drug_name`. `DocumentRow` satisfies it structurally, so no field is re-declared and a
rename in the row model fails the type check rather than drifting; inside `chat/`, reading
any other document field is a mypy error. Retrieval returns `ScoredChunk` (a `ChunkRow`
plus its scores) and does not carry the document, so joining chunk to document is
`chat/join.py`'s job, called from `prepare_turn()`.

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
is also where the relevance threshold lands: filtering to zero produces the decline path
with no extra branch and no generation spend.

**A failure partway through a stream ends in `error`, not `done`.** The client has already
rendered part of an answer, so a dropped generation call emits an `error` event carrying a
canned message rather than truncating silently — the mid-stream case the assignment names.

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

## Eval harness

Its own project feature and the heaviest-weighted piece of engineering. Requirements:
≥15 authored question/expected-answer pairs, including ≥3 unanswerable from the corpus,
≥2 requiring synthesis across multiple documents, and ≥2 personal-medical-advice
questions the app must decline. It scores **both** retrieval quality (hit rate / MRR
against expected sources) and answer quality, runs from a single command, and prints a
report. If time runs short, cut a UI feature — never the eval harness.

**It runs in-process — no HTTP, no running server.** The harness is a backend package,
`backend/eval/`, run as `python -m eval` from `backend/` — or as `make eval` from the
repo root, a one-line `Makefile` target that is the assignment's "single command" and
holds no logic of its own (kept out of the deployed image via `.dockerignore`, out of
the repo's history via a gitignored `eval/runs/`). It calls
`prepare_turn()` — the same single function the query endpoint composes its response
from — and opens its own psycopg connection (hosted Supabase) and model clients. It
measures the path users get because there is only one path to call; a refused case
needs no special handling in the driver, because a refusal is just a `Turn` with no
query and no chunks. The one part it does not exercise is the conversation-history write,
deliberately — a full run is ~72 pipeline calls and must not bury the shared history
in robot conversations — and that write is covered by unit tests. This supersedes
driving the endpoint's `?trace=true` mode over HTTP; the harness no longer consumes
trace mode (whether the endpoint keeps it as a debug affordance is an endpoint
question, to reconcile at the API merge).

**Suite:** 18 single-turn cases in `eval/suite.py` as typed literals (mypy checks
ground truth at author time): 7 single-section/table lookups, 3 cross-document
synthesis, 3 discrimination traps carrying `forbidden_drugs`, 3 unanswerable (the
deliberately-cut drugs and excluded-section content), 2 personal-advice refusals. An
expected source is `(document_id, drug, section_number)`.

**Scoring (built — `eval/scoring/`, pure, hermetic, in CI):** Recall@K, MRR,
Precision@K, each under two lenses — **strict** (exact document) and **lenient** (any
sibling label of the same drug) — at document and section granularity. Six of ten
drugs have sibling labels, so the lenses genuinely differ; the gap between them is
itself a reported finding. Behavioral checks: advice cases must be gate-refused with
the advice refusal itself (a fail-closed refusal does not pass), unanswerables must
end in the canned no-context message or a generated does-not-cover admission,
discrimination traps (sertraline vs escitalopram, warfarin vs apixaban) must serve no
forbidden drug. Grounding: every emitted tag resolves to a served chunk. Answer
quality: the **eval-side judge** — `gpt-5` via `ChatOpenAI.with_structured_output`,
deliberately stronger than the generator — scores each answer against the expected
answer and the served excerpts; automated and mandatory (distinct from the optional
live-pipeline judge, which only annotates).

**Configurations (`eval/configs.py`):** two per case — **dense** (baseline) and
**dense+sparse+rerank** (everything on) — the stretch goal's graded before/after. The
single-leg middle configurations were dropped: they doubled the run to attribute the
gain between the sparse leg and the reranker, and on 13 scored cases a one-case swing
moves Recall@5 by 0.08, which exceeds the gap they existed to show. Gate and rewriter
stay on throughout: the advice cases need the gate, and on a single-turn suite the
rewrite delta would measure only normalization (recorded limitation).

**Report shape (`eval/report.py`, pure — traces and verdicts in, markdown out):** the
report **states its own criteria before any result** — what the suite is made of (counted
from the cases, so the prose cannot go stale, with each kind's mean chunk hit rate per
configuration beside it, so a weak *question type* is visible before any aggregate is
read), what each metric means and how it can mislead, the pass condition for every behavioral check, what is recorded as a failure,
and what the sample size does not establish. A saved run is read on its own by a grader,
so it must not require `DESIGN.md` to be interpretable. Then one section per
configuration — rank metrics, behavior checks, judge counts, a per-query
chunk hit-rate bar chart, then that configuration's failures — followed by a single
**Comparison** section that puts the configurations side by side: rank metrics with the
best marked, behavior and judge counts, a per-case movement chart, and a histogram
binning the cases by chunk hit rate so a configuration's misses show as mass in the low
band rather than only as a lower mean. **Every side-by-side table carries a signed `Δ`
column** against the baseline configuration — a fraction for rank metrics, whole cases
for behavioral counts — so no reader has to subtract, and the movement chart names the
individual cases that regressed, which an aggregate cannot show.

The register is technical: metric names, lens names, and delta notation are used as such,
each defined once at the point the reader meets it. Charts are ASCII inside fenced blocks,
so the report renders identically in a terminal and in markdown. Progress during a run is
a rewritable bar on **stderr** — stdout carries only the report, and `main()` reconfigures
stdout to UTF-8 so `make eval > report.md` cannot fail on a character outside the console
codepage.

**Record/replay:** a run saves every trace to `eval/runs/<timestamp>.json`;
`--score-only <run>` re-scores a saved run offline, so scoring and judge iteration
cost zero pipeline calls. The saved run backs the failure analysis.

**Build state:** the harness is fully built — contracts, `scoring/` (in CI), `judge.py`,
`report.py`, `driver.py` (reuses the API's composition root, `build_clients`), and
`python -m eval` with a guard that refuses to run while `suite.py` still contains
authoring placeholders. The 18 cases are drafted with every expected source verified
against extracted label text (pending owner review — see `AI_USAGE_RECORDS.md`); what
remains before a real run is an ingested corpus, and the driver is unexercised against
live data until ingestion has run.

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
pytest (hermetic only); ingestion — the same three, plus ruff and mypy over the upload
script, and deliberately *without* `--group extraction`, so no CV model weights are
downloaded and no test can quietly depend on them; frontend — eslint, tsc, vitest,
build. All three jobs run unconditionally on every PR (no path filtering). No secrets
in CI.

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
- The query gate and query rewriter still call the OpenAI SDK directly, so the "every
  LLM call goes through `ChatOpenAI`" rule is true of generation and not yet of them.
  Retrofit is two `with_structured_output` swaps plus an `isinstance` narrow at each
  tool's existing failure branch; it was left out of the generation branch to avoid
  colliding with the retrieval session working in those files.
- The live LLM-as-judge is not built. `DoneEvent.judge_grounded` is the typed slot it
  would fill and currently always serializes as `null`.
- **The carving rules are validated against `pypdf` text, not against live `hi_res`
  output.** Every boundary rule was checked over all 17 PDFs, but through a different
  extractor than the one that ships. `hi_res` returns better reading order and real
  element categories, so the rules should hold or improve — but the first real run is
  the first time the two meet. That run is the next step, and it is where a surprise
  would appear.
- Ingestion has no live smoke test yet. The hermetic suite covers the pure stages; the
  adapters (`extraction`, `storage`, `embedding`, `identity`, `registry`) are exercised
  only by an actual run.
- The bucket listing reads a single page of results. Correct for 17 documents, wrong
  somewhere past the API's default page size — one of the concrete things "scaling to
  10,000 documents" has to fix.
- **The frontend casts API responses instead of validating them.** There is no runtime
  schema layer, so the backend row models are enforced on their side of the wire and
  nowhere on this one. A renamed field becomes `undefined` inside a component rather than
  a typed error at the boundary — the opposite of the backend's stated adapter discipline,
  accepted because the corpus of callers is small and the cost of a schema library was
  judged not worth it for a demo.
- **The frontend has no mock backend outside tests.** `npm run dev` renders a UI wired to
  a backend that must actually exist. The first real HTTP request the client ever makes
  will be on cutover day.
- The assistant messages the client renders after a stream are built locally rather than
  re-fetched, so a conversation's cached view is the client's reconstruction until the
  next full load. It matches what the backend persisted at `done`; it is not read back to
  prove it.

## Two things to design for now, without building them

- **Query decomposition for multi-hop questions.** The eval's clearest failure
  (`synthesis-warfarin-amiodarone`) is one query matching a single document on both
  entities and swallowing every slot. The fix is decomposition into per-document
  sub-queries, or a per-document quota in fusion. Neither is built; the failure is
  characterized above and the shape of the fix is known.
- **Every significant line must be defensible out loud.** Prefer the version that can be
  explained over the version that is clever.

## Other graded surface

A README covering local setup, ingestion, and evals; CI on push; and the **commit history
itself** — a coherent sequence of commits, not one large dump.
