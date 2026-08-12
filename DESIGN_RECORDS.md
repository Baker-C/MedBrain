# DESIGN_RECORDS.md

Running record of architectural decisions, rejected tradeoffs, eval failure analysis,
next steps, and known shortcuts. Append-only. Every entry carries one timestamp
representing both when the decision was made and when it was recorded.

---

## No caching layer, frontend or backend

**Timestamp:** 2026-08-11 ~21:20 -07:00 (approximate — recorded in a parallel session
earlier this evening; exact minute not recoverable)

**Decision:** Build no caching layer anywhere in MedBrain. Five specific caches were
considered and all five were rejected.

**Rejected, with reasons:**

1. **Query embedding cache** (`lru_cache` over `embed_query`). Rejected despite being
   ~10 lines and having zero correctness risk — a query embedding is a pure function of
   (text, model), independent of retrieval config. It was rejected on scope, not on
   safety: the eval suite runs 15+ questions across 3 configs, so the saving is a few
   dozen embedding calls per run, which is not worth a layer a reader has to reason
   about. Revisit only if eval iteration cost becomes a real bottleneck.

2. **Retrieval result cache** (query → retrieved chunks). Rejected on correctness. Keyed
   on the query alone it would serve `dense` results while `hybrid` or `hybrid+rerank`
   is being measured, silently flattening the before/after hybrid deltas the assignment
   requires — and it would fail as a *finding* ("rerank didn't help"), not as an error.
   A correct key needs query + config + top_k + rerank model + embedding model + corpus
   version, threaded through a pipeline whose entire purpose is being swappable.
   Secondary reason: retrieval latency is itself an eval metric, so caching retrieval
   would mean measuring cache hits instead of retrieval.

3. **Full LLM response cache.** Rejected on three independent grounds. (a) A cached
   response has no token stream — replaying it as one chunk destroys TTFT and hides the
   mid-stream failure handling that is separately graded. (b) Same config-bleed hazard as
   #2 unless the key includes retrieved chunk ids and full generation config. (c) It
   freezes answer variance, which is what the eval suite exists to observe. The cost
   motivation behind it is served instead by the eval harness writing per-run results
   artifacts — a record of a measured run, not a substitute for one.

4. **LangChain `set_llm_cache()` (`InMemoryCache` / `SQLiteCache`).** Rejected on
   legibility and on near-zero payoff. It is a global singleton that silently changes
   what an endpoint returns, with no local signal at the call site — bad in a project
   graded on defensible-out-loud code. Its key is the prompt string, which here contains
   retrieved chunks *and* shared conversation history, so two identical user questions
   produce different keys and rarely collide. Not directly eval-corrupting (differing
   configs produce differing prompts), but it buys almost nothing and costs clarity.

5. **Anthropic-style provider prompt caching.** Rejected as premature: the system prompt
   and per-turn context are small, and the demo has no traffic.

**Not a cache, still in scope:** ingestion idempotency. Chunks carry
`content_hash = sha256(embedding_model_id + chunk_text)` under a unique constraint, and
ingestion inserts with `ON CONFLICT DO NOTHING`. This satisfies the spec requirement that
re-running the pipeline must not duplicate data. The model id is part of the hash so that
swapping the embedding model cannot silently reuse stale vectors. That it also avoids
re-embedding unchanged chunks is a side effect of correct idempotency, not a performance
feature.

**Why this fits the corpus and use case:** the corpus is 15–30 documents and the app has
one user at a time with no auth. There is no traffic pattern that a cache would serve.
The only workload that repeats is the eval suite, and that is precisely the workload where
a stale cross-configuration result would corrupt the primary deliverable.

---

## Hybrid retrieval as the single stretch goal

**Timestamp:** 2026-08-11 21:31 -07:00

**Decision:** hybrid retrieval — dense vectors combined with keyword search, then a rerank
stage. The assignment permits at most one stretch goal, and this is it.

**Reasoning:** this is medical software. Precise, accurate, specific retrieval outranks
breadth of features even in a short demo, because a clinical operations user acting on a
near-miss passage is a worse outcome than a user missing a feature. Spending the one
stretch goal on retrieval accuracy therefore follows from the domain, not from taste.

**Rejected, with reasons:**

1. **Query decomposition for multi-hop questions.** The eval set requires ≥2 questions
   needing synthesis across documents, so this is directly relevant — and it was still
   rejected, because better ranking improves every one of the 15+ questions while
   decomposition improves only the multi-hop subset. Hybrid retrieval is the broader lever
   on the same corpus.
2. **Structured extraction endpoint (JSON schema per document).** A side feature that does
   not touch the graded answer path — grounding, honesty, refusal, citations. It would
   demonstrate schema validation and nothing that is weighted.
3. **Observability / tracing.** Genuinely useful and the most tempting rejection, since
   per-request chunk and latency visibility would help the failure analysis. Rejected
   because the eval harness already produces the numbers the failure analysis needs, so
   tracing would duplicate that at the cost of the one stretch slot.
4. **Picking two stretch goals.** The assignment says pick at most one and asks for depth
   over breadth. Two shallow stretch goals read worse than one deep one.

---

## Supabase Postgres with pgvector as the single store

**Timestamp:** 2026-08-11 21:31 -07:00

**Decision:** one Supabase Postgres instance holds everything — documents, chunks,
embeddings (`pgvector`), and conversations. No separate vector database.

**Rejected, with reasons:**

1. **A dedicated vector DB (Qdrant, Weaviate, Chroma, Pinecone) alongside Supabase.**
   Rejected because Supabase is already required for conversation storage, so adding a
   second store creates a consistency problem — two systems to keep in sync on every
   re-ingestion, and two places for a chunk to exist with different metadata. At 15–30
   documents there is no recall or latency benefit to buy in exchange for that.
2. **Chroma alone, dropping Postgres.** Rejected because conversations and app data still
   need a relational home, and Chroma is not it.

**What this buys retrieval:** dense search and keyword search live in the same table, so
hybrid retrieval fuses two rankings inside one SQL query instead of across a network
boundary. Citation metadata (document, section, page) sits on the same row as the vector,
so a citation cannot drift from the chunk it came from.

**Known scaling limit:** this is the correct choice at 15–30 documents and is not
automatically correct at 10,000. `pgvector` index tuning and Postgres full-text ranking
both degrade differently than a purpose-built vector store under that load — see the next
steps section when it is written.

---

## Keyword search: `ts_rank` first, `rank_bm25` measured against it

**Timestamp:** 2026-08-11 21:31 -07:00

**Decision:** implement the keyword half of hybrid retrieval with Postgres full-text
search and `ts_rank` first. Add `rank_bm25` afterward and measure both with the eval
harness rather than choosing between them on argument.

**The honest caveat, stated up front:** `ts_rank` is **not** BM25. It does not do BM25's
document-length normalization or term-saturation weighting. Describing a `ts_rank`
implementation as "BM25" would be inaccurate, and the assignment names BM25 specifically.

**Rejected, with reasons:**

1. **Going straight to `rank_bm25` and skipping `ts_rank`.** Rejected because `ts_rank`
   comes free with the store already chosen and runs in the same query as the vector
   search, making it the fastest path to a working hybrid pipeline. It also becomes the
   baseline the real BM25 is measured against.
2. **Declaring `ts_rank` sufficient and never adding BM25.** Rejected because the eval
   deltas are the point of the stretch goal, and an in-process `rank_bm25` over a corpus
   this small is cheap enough that not measuring it would be a gap, not a shortcut.

**Debt this creates:** `rank_bm25` in Python holds the chunk set in memory and re-ranks
outside the database. That is defensible at this corpus size and does not survive to
10,000 documents. If BM25 wins the comparison, the production answer is a real BM25 index
in the database, not the in-process version.

---

## Retrieval as a pluggable pipeline with configuration as an explicit input

**Timestamp:** 2026-08-11 21:31 -07:00

**Decision:** retrieval is a pipeline of steps that swap in and out by configuration, and
it must run in at least `dense`, `hybrid`, and `hybrid+rerank` modes. Retrieval
configuration is passed in explicitly and is never ambient state — no module-level
default, no environment variable read at call time, no global set once at startup.

**Why:** the assignment requires showing eval deltas before and after hybrid retrieval.
That means one process runs the same questions under multiple configurations and reports
them side by side. Ambient configuration makes that either impossible or quietly wrong,
and a quietly wrong version corrupts the primary deliverable rather than failing loudly.

**Rejected, with reasons:**

1. **A single hardcoded retrieval path.** Simpler, and it makes the required before/after
   comparison unmeasurable. Rejected outright.
2. **An environment-variable switch between modes.** Rejected because comparing modes then
   requires separate processes and manual result stitching, and because it is exactly the
   ambient state that lets a stale configuration leak into a measurement.

**Consequence recorded on purpose:** this is also where a relevance threshold below which
the app declines to answer will drop in. The assignment pre-announces that as a live
interview modification, so the seam exists deliberately. It is not implemented yet.

---

## No authentication; shared conversation history

**Timestamp:** 2026-08-11 21:31 -07:00

**Decision:** no auth, no accounts. The app is open and every conversation is visible to
everyone. Supabase is used as plain storage, with its auth left switched off.

**Rejected, with reasons:**

1. **Supabase auth with per-user history.** Rejected on scope. The assignment requires
   conversation history *within a session* and nothing more, and multi-tenancy is
   explicitly listed as a "what would you do next week" item rather than a deliverable.
   Building login earns nothing on the rubric while consuming hours the eval harness needs.
2. **OAuth via an external provider.** Rejected for the same reason, with more setup cost.

**Debt this creates, acknowledged:** shared global history is not a design anyone would
ship. It is a deliberate demo simplification, and multi-tenancy belongs in the next-steps
section — row-level tenancy on the conversation tables plus per-tenant corpus isolation.

---

## Render for deployment; Vercel rejected

**Timestamp:** 2026-08-11 21:31 -07:00

**Decision:** deploy on Render, frontend and backend together.

**Rejected, with reasons:**

1. **Vercel.** The initial preference, rejected on a concrete technical limit rather than
   taste: Vercel's Python serverless functions have a deployment size cap that FastAPI +
   LangChain strains and that a local cross-encoder reranker (`sentence-transformers`,
   which pulls in torch) would exceed. Serverless cold starts on a token-streaming
   endpoint are a second strike. Keeping the reranker in the backend was the higher
   priority, so the platform gave way.
2. **Split deploy — frontend on Vercel, backend on Fly.io or Render.** Viable and
   rejected for operational simplicity: one platform and one deploy for a demo, rather
   than two dashboards and a cross-origin configuration.

---

## Frontend and backend boundary

**Timestamp:** 2026-08-11 21:31 -07:00

**Decision:** one repository, `frontend/` and `backend/`. The frontend reaches the backend
only through API endpoints. All retrieval, reranking, and generation live in the backend.

**Why:** it keeps API keys server-side, which the assignment requires explicitly. It also
keeps the entire graded surface — chunking, hybrid retrieval, reranking, grounding,
refusal — in one language and one place, so the eval harness exercises the same code path
the UI does rather than a parallel implementation.

**Rejected, with reasons:**

1. **Separate repositories for frontend and backend.** Rejected as overhead with no
   benefit at this size; it also fragments the commit history, which is itself graded.
2. **Any retrieval or reranking logic in the frontend.** Rejected because it would move
   provider keys or embedding calls client-side and would give the eval harness a
   different code path than the UI, making eval results non-representative.

---

## Corpus curated: 23 DailyMed FDA drug-label PDFs

**Timestamp:** 2026-08-12 03:25 -07:00 (corpus assembled ~2026-08-11 19:19–19:41, curated ~03:19; recorded now)

**Decision:** the corpus is 23 PDF drug labels from DailyMed covering 13 drugs, committed
in `DocumentCorpus/`. Six documents from the first cut were removed: four 2-page API
powder/compounder labels (Mirtazapine_2, Mirtazapine_3, Sertraline_2, Trazodone_2), the
2-page compounder Amiodarone (replaced by the full Slate Run label), and the 25-person
ANSI first-aid kit that had been misfiled as Aspirin_2 (replaced by the
acetaminophen/aspirin/caffeine label, formerly Aspirin_3).

**Why:** the powder labels had no clinical sections — nothing retrievable, nothing
citable — so they could only ever add near-duplicate title noise to retrieval. The
first-aid kit was not an aspirin document at all; five actives, none of them the drug in
its filename, which would have poisoned `drug_name` metadata and the discrimination evals.

**Deliberately kept as hard cases:** two old-format Albuterol labels (no numbered
sections), two OTC Aspirin labels (Drug Facts format + carton text), and TRAZAMINE (a
co-packaged trazodone product with idiosyncratic headings). Handling their quirks is part
of what is graded; a corpus of only clean PLR labels would be too easy.

---

## Embedding model: text-embedding-3-large truncated to 1536 dimensions

**Timestamp:** 2026-08-12 03:25 -07:00 (decided in Build-Spec revision ~01:53; recorded now)

**Decision:** OpenAI `text-embedding-3-large` with the API's native `dimensions: 1536`
parameter; the pgvector column is `vector(1536)` with an HNSW index.

**Rejected, with reasons:**

1. **Native 3072 dimensions.** pgvector's HNSW and IVFFlat indexes cap at 2000
   dimensions — a 3072-dim column is storable but unindexable, forcing a sequential scan
   on every query. Survivable at ~2k chunks, but a known landmine accepted for no gain.
2. **`text-embedding-3-small` at native 1536.** The large model is Matryoshka-trained, so
   its leading 1536 dimensions outperform the small model at the same width — same
   storage cost, better quality.
3. **Local embedding models.** Would fatten the lean backend container (the same reason
   the cross-encoder reranker was rejected) for no measured quality win on this corpus.

**Consequence:** embedding config is fixed; changing model or width means re-embedding
everything, which the registry-driven reconciliation treats as a full re-ingest.

---

## Chunking: two-pass structure-aware, ~1500 chars, in-section overlap only

**Timestamp:** 2026-08-12 03:25 -07:00 (decided in Build-Spec revision ~01:53; recorded now)

**Decision:** Pass 1 carves each document into real sections from detected headers
(capturing section number + title); Pass 2 runs the recursive splitter per section
(~1500-char target). A fitting section stays one chunk. Section header text is repeated
at the top of every sub-chunk. Overlap exists only within a subdivided section — never
across a section boundary, so no chunk can straddle two citable sections. Tables are
atomic: pulled out in Pass 1, serialized from Unstructured's HTML, split by row groups
with the header row repeated only when oversized. Extraction is Unstructured `hi_res`
(local CV layout models), chosen because tables carry the answer in most of these labels.

**Rejected, with reasons:**

1. **Naive RecursiveCharacterTextSplitter over the whole document.** Chunks would bleed
   across section boundaries, making the section citation on a chunk ambiguous or wrong —
   and honest citations are the point.
2. **One-chunk-per-section with no size cap.** Section sizes in this corpus run from one
   sentence (13.1 Carcinogenesis) to thousands of chars (6 Adverse Reactions); wildly
   uneven chunks degrade dense retrieval comparability.
3. **Text-only extraction (pypdf / pdfplumber).** Flattens tables into word soup;
   dosage/interaction tables are exactly where answers live.
4. **A multi-strategy chunking bake-off.** Out of scope for the time box; one defensible
   strategy, measured well, beats two measured thinly.

---

## Idempotency: registry-driven reconciliation (supersedes ON CONFLICT hash-skip)

**Timestamp:** 2026-08-12 03:25 -07:00 (decided in Build-Spec revision ~01:53; recorded now)

**Decision:** supersedes the 2026-08-11 design (content_hash unique constraint +
`ON CONFLICT DO NOTHING`). A `documents` registry table stores each document's raw-file
SHA-256 and ingestion state. Corpus-level reconciliation: new docs ingest; byte-identical
docs skip entirely (including hi_res extraction); changed docs reconcile chunk-by-chunk
(unchanged content-hashes kept, orphans deleted, new chunks embedded); removed docs get
their chunks deleted. Chunk changes + registry update commit in one transaction per
document.

**Why the old design lost:** hash-skip only prevents duplicates. It never deletes — edit
a PDF and re-run, and stale chunks from the old version keep answering queries; remove a
document and its chunks live forever. "Idempotent" has to mean the DB converges to the
corpus folder, not merely that inserts don't double.

**Also changed:** the chunk hash is now content-only. The embedding model id was dropped
from the hash because the config is fixed and any embedding change invalidates every
vector anyway — a full re-ingest, which the registry handles.

---

## Hybrid fusion: Reciprocal Rank Fusion, k=60

**Timestamp:** 2026-08-12 03:25 -07:00 (decided in Build-Spec revision ~03:19; recorded now)

**Decision:** dense (HNSW cosine) and sparse (`websearch_to_tsquery` + `ts_rank` over a
generated `tsvector` column, GIN-indexed) each pull ~top 30–50 in parallel from the same
chunk table; fusion sums `1/(k+rank)` with k=60 and keeps ~top 20. A chunk on both lists
gets both contributions — agreement boosts.

**Rejected, with reasons:**

1. **Weighted score blending.** Cosine similarity and `ts_rank` live on incompatible,
   corpus-dependent scales; blending needs calibration that would itself need evals. RRF
   uses rank position only — one tunable constant, well-studied defaults.
2. **Dense-only (dropping the sparse leg).** Drug labels are full of exact tokens that
   carry the answer — drug names, IR/SR/XL, section numbers, doses — which lexical search
   matches sharply and embeddings blur. Sparse is also the direct defense for the
   look-alike discrimination traps (sertraline vs escitalopram).

---

## Reranker: self-built LLM reranker, batched pointwise, sort in code

**Timestamp:** 2026-08-12 03:25 -07:00 (decided in Build-Spec revision ~03:19; recorded now)

**Decision:** one LLM call scores all ~20 fused candidates against the query (short ids
c1..c20, structured JSON scores 0–10, temperature 0). Code — not the model — does the
reordering: sort by score, tie-break on fused RRF rank, keep top ~5–8. Malformed JSON or
missing scores fall back to the fused RRF order. Toggleable, so the eval harness measures
it on vs off.

**Rejected, with reasons:**

1. **Local cross-encoder (sentence-transformers).** Pulls torch + weights into the
   backend container — the exact bulk that drove the Vercel rejection — and breaks the
   lean-backend split (the serving container must never carry ML weights).
2. **Hosted rerank API (Cohere).** A second vendor + key for one call; owning the logic
   is worth more in a project graded on defensible-out-loud code.
3. **Listwise LLM rerank (model returns an ordering).** A returned permutation can drop
   or hallucinate ids silently; pointwise scores map 1:1 to ids, keep a numeric trace for
   the eval report, and fail loudly.

---

## Streaming and citations: SSE, mapping-first, [[Sn]] sentinels, client-side resolution

**Timestamp:** 2026-08-12 03:25 -07:00 (decided in Build-Spec revision ~03:19; recorded now)

**Decision:** the query endpoint streams SSE: event 1 is the full tag→citation mapping
(known at context-assembly time, before generation), then raw tokens with `[[Sn]]`
sentinels passed through untouched, then `done` (carrying post-hoc annotations like the
optional live-judge flag) or `error`. The client buffers split sentinels and resolves
tags against the mapping it already holds. Gating decides what streams before tokens
flow. Trace mode returns a single JSON payload instead — the eval harness's input.

**Rejected, with reasons:**

1. **Backend post-hoc tag expansion (the original 8.2 design).** Rewriting the answer
   after generation is incompatible with token streaming — the collision was caught at
   design time and resolved by moving resolution client-side.
2. **Prose source tags ("source 1").** Tokenizes unpredictably; a delimited sentinel is
   parseable in a token stream.
3. **WebSockets.** Bidirectional transport for a one-directional stream; SSE is simpler.

---

## Eval judge: automated, eval-side, mandatory in the harness

**Timestamp:** 2026-08-12 03:25 -07:00 (decided in Build-Spec revision ~03:19; recorded now)

**Decision:** answer quality is scored by an LLM-as-judge that lives inside the
verification harness, comparing each answer against the hand-written expected answer and
the retrieved sources, aggregated in the single-command report. It is distinct from the
optional live-pipeline judge (8.4), which only annotates user-facing answers post-stream.

**Rejected, with reasons:**

1. **Human-graded accuracy as the mechanism of record (the original 10.3 design).** The
   assignment requires *automated* answer-quality scoring run by a single command; hand
   grading fails that requirement on its face. Human spot-checks remain as a supplement,
   never the mechanism.

**Open:** which model judges. It should not be the same model that generates, or
self-preference bias inflates every score.

---

## Keyword leg is ts_rank only — the rank_bm25 comparison is dropped

**Timestamp:** 2026-08-12 04:17 -07:00

**Decision:** the sparse half of hybrid retrieval is Postgres full-text `ts_rank`, full
stop. The 2026-08-11 plan to add `rank_bm25` and measure it against `ts_rank` is
**superseded** — no BM25 implementation, no bake-off.

**Why:** scope. The eval delta the assignment grades is *hybrid vs dense* — the stretch
goal's before/after — not ts_rank vs BM25, which was a self-imposed second comparison.
The hours it would take belong to the eval harness. The honesty caveat survives in
`DESIGN.md`'s debt list: `ts_rank` is not BM25 (no document-length normalization, no term
saturation) and must never be described as BM25; at 10,000 documents the production
answer is a real BM25 index.

**Rejected:** keeping the comparison (costs eval-harness hours for an unweighted
finding); in-process `rank_bm25` as the shipped leg (out-of-database ranking, worse
operationally than `ts_rank` in-query, and previously flagged as non-shippable debt).

---

## Corpus PDFs live in a private Supabase Storage bucket; citations click through via signed URLs

**Timestamp:** 2026-08-12 04:17 -07:00 (decided in Build-Spec revision earlier this session; recorded now)

**Decision:** the corpus source of truth is a private Supabase Storage bucket
(`documents/{document_id}.pdf`); `DocumentCorpus/` in the repo is the seed copy, pushed
by a one-time local upload script that touches storage only. The `documents` registry
stores each object key. Ingestion reconciles against the bucket. A citation click calls
`GET /documents/{id}/source-url`; the backend mints a ~5-minute signed URL and the client
opens the PDF directly from Storage in a new tab. Credential map: upload script — storage
write; ingestion — storage read + Postgres write; backend — Postgres read + URL minting;
frontend — no credentials.

**Rejected, with reasons:**

1. **Serving PDFs as static files from the backend.** Puts file bytes through the lean
   serving container and couples the deployed image to the corpus contents.
2. **A public bucket.** Free, but "unlisted app" is not an access policy; signed URLs
   cost one endpoint and keep the bucket closed.
3. **PDF bytes as `bytea` in Postgres.** Bloats the database that also serves vector
   search; blobs belong in object storage, pointers in the DB.
4. **Repo-only corpus with no hosted copy.** The deployed app could not open a citation's
   source document at all — citations would dead-end.

---

## Gating moved to the front of the pipeline, before embedding and retrieval

**Timestamp:** 2026-08-12 04:17 -07:00

**Decision:** the medical-advice gate runs in the front stage alongside query rewriting,
on the raw query (+ conversation history), before anything is embedded or retrieved. A
flagged question short-circuits: the user gets a pre-written refusal response, streamed
with an empty sources mapping, and no retrieval or generation runs. Gating always
executes even when the query rewriter is toggled off — the rewrite is optional, the gate
is not. This supersedes the Build-Spec §8.3 wording ("a decision made while producing
the answer").

**Why:** compute and coherence. A refused question spends zero embedding/retrieval/
generation. And the refusal decision depends only on the question itself — personal
medical advice is identifiable from the query — so nothing is lost by deciding before
retrieval. It also dissolves the §8.3/§8.5 contradiction (decide-during-generation vs
gate-before-streaming) in favor of the cleaner reading.

**Rejected, with reasons:**

1. **Gating inside the generation prompt.** One fewer LLM call, but the refusal becomes
   a probabilistic behavior of the answer model mid-stream — untestable as a distinct
   layer, and full retrieval cost is paid before refusing.
2. **Gating after retrieval.** No benefit: the decision doesn't use retrieved content.

**Debt accepted:** an extra front-stage LLM decision on every query (latency). Trade
accepted for the refused-query savings and a separately testable, swappable gate.

---

## Citation precision: graceful fallback from section to document

**Timestamp:** 2026-08-12 04:17 -07:00

**Decision:** a citation is document + section number/title when the chunk has a carved
section; document only when it doesn't. Section metadata fields are nullable by design.
No page numbers in citations.

**Why:** the corpus guarantees section structure only for the 17 PLR labels; the
old-format Albuterol labels, the OTC Drug Facts labels, and TRAZAMINE may carve without
numbered sections. A citation that pretends to precision it doesn't have is worse than
one that is honestly coarser.

**Rejected:** page numbers as the fallback tier (document + page when section is
missing). Cheap at extraction time — Unstructured elements carry `page_number` — but
cut for scope. Recorded in `DESIGN.md` debt as the obvious upgrade if fallback-quality
citations matter later.

---

## Testing architecture: logic/adapter split; hermetic CI; live health checks separate

**Timestamp:** 2026-08-12 04:17 -07:00

**Decision:** every backend feature separates pure, typed logic (no I/O) from thin
adapters that call OpenAI/Supabase/Storage. Unit tests run against the logic with typed
fixtures and no network; they are what CI runs. External responses are validated at the
adapter boundary; unexpected shapes become graceful typed errors that feed the API's
error states. A separate small health-check suite verifies live connections (DB, bucket,
OpenAI key) and runs locally / post-deploy — never in CI. CI on push (GitHub Actions):
ruff + mypy + pytest for the backend; eslint + tsc + build for the frontend. No secrets
in CI.

**Rejected, with reasons:**

1. **API-hitting tests in CI.** Flaky, needs secrets in the pipeline, costs money per
   push, and tests the vendor more than the logic.
2. **Deep-mocking services inside logic tests.** If logic needs a mocked client, the
   logic and the I/O weren't separated; the fix is the split, not better mocks.
3. **Coverage-chasing.** The assignment grades the *right* handful of tests explicitly,
   not exhaustive coverage.

---

## Persistent disclaimer banner + flag-response — both, not either

**Timestamp:** 2026-08-12 04:26 -07:00

**Decision:** the responsible-scoping requirement is satisfied by two separate pieces:
an always-visible static disclaimer banner in the UI ("document-lookup tool for
professionals — not medical advice"), and the pre-written flag-response returned by the
front-stage gate when a question asks for personal medical advice.

**Rejected:** flag-response only (the initial position). The assignment's wording is "a
persistent disclaimer **plus** a refusal path" — the flag-response is the refusal path,
and a disclaimer shown only on flagged questions is by definition not persistent. The
banner costs roughly two lines of Tailwind; skipping a named, graded requirement to save
them is not a trade.

---

## Models: gpt-5-mini generation, gpt-5-nano reranker, gpt-5 eval judge

**Timestamp:** 2026-08-12 04:26 -07:00

**Decision:** all three LLM roles use OpenAI — one SDK, one key, keys server-side.
Generation: `gpt-5-mini` (streams, cheap; grounded extraction over 5–8 provided chunks
does not need a frontier model, and the assignment explicitly blesses small models).
Reranker: `gpt-5-nano` (scores ~20 short passages 0–10 as JSON; the cheapest model that
returns clean structured output wins — latency matters more than depth). Eval judge:
`gpt-5` (full) — the judge is deliberately a stronger model than the generator it
scores, and its cost is bounded by suite size (~20 prompts per eval run), not by user
traffic.

**Rejected, with reasons:**

1. **One model everywhere (gpt-5-mini).** Simplest, but an equal-strength sibling
   judging the generator weakens the credibility of the eval suite — the
   heaviest-weighted deliverable.
2. **Cross-provider judge (a Claude model).** The most defensible judge methodologically
   — a different model family has no self-preference toward the generator's phrasing —
   but it costs a second SDK, key, and billing account in a time-boxed build.

**Known limitation, recorded on purpose:** judge and generator share a provider and a
model family. Same-family self-preference bias is documented (a stronger judge reduces
but does not eliminate it), so eval-judge scores should be read as relative across
configurations, not as absolute quality. State this in the failure-analysis section of
the graded DESIGN.md.

---

## Front-stage rewrite + gate uses the generation model (gpt-5-mini)

**Timestamp:** 2026-08-12 04:28 -07:00

**Decision:** the front-stage call that gates and (when toggled on) rewrites the query
runs on `gpt-5-mini` — the same model as generation. Three model configs total:
`gpt-5-mini` (generation + rewrite/gate), `gpt-5-nano` (reranker), `gpt-5` (eval judge).

**Rejected, with reasons:**

1. **`gpt-5-nano` for the front stage.** Cheapest, and fine for rewriting — but the gate
   is a graded safety behavior, and a gate false-negative (personal-advice question
   answered) is a rubric failure. The floor model is the wrong place to save fractions
   of a cent per query.
2. **A fourth, separately-chosen model.** More configuration surface with no argument
   for it; reusing the generation model keeps the model map explainable in one sentence.

---

## Page deep-linking — supersedes "no page numbers" (2026-08-12 04:17)

**Timestamp:** 2026-08-12 04:28 -07:00

**Decision:** every chunk records **`page_start` and `page_end`** at ingestion, taken
from Unstructured's per-element `page_number` (a stitched cross-page table spans pages;
the deep link uses `page_start`). On citation click, the client appends `#page=N` to the
minted signed URL — the fragment is client-side only, so it cannot break the URL
signature — and the PDF opens on the cited page in Chromium/Firefox viewers (Safari
ignores `#page=` and degrades to page 1). The citation precision ladder becomes:
document + section + page → document + page (sectionless labels) → document only.

**Why the reversal:** the earlier entry cut page numbers on scope and named them "the
obvious upgrade if fallback-quality citations matter." They matter — the sectionless
documents (old-format Albuterol, OTC Aspirin, TRAZAMINE) would otherwise cite to a bare
document with no way to land the reader anywhere, and the assignment words the citation
requirement as "section/page." The cost is two integer columns and reading a field
Unstructured already emits.

**Rejected:** section-only citations (the superseded 04:17 decision); PDF.js embedded
viewer for guaranteed page landing across all browsers (a whole viewer dependency to fix
Safari's fragment handling — not worth it for a demo).

---

## Schema: typed columns, identity/location split — no JSON metadata blob

**Timestamp:** 2026-08-12 05:11 -07:00

**Decision:** all chunk and document metadata lives in typed Postgres columns. Document
identity (drug name, manufacturer, formulation) is stored once on `documents`; chunks
carry only per-chunk location (section number/title, page start/end, chunk index, chunk
type). A citation joins chunk → document. This replaces Build-Spec §5's "JSON metadata
column".

**Rejected, with reasons:**

1. **A `jsonb` metadata blob per chunk.** The promised drug/formulation filtering becomes
   stringly-typed (`metadata->>'drug_name'`), needs a jsonb GIN index to be fast, and a
   mistyped key matches nothing silently. mypy — a graded deliverable — sees
   `dict[str, Any]` and verifies none of the metadata the citations depend on. JSON is
   for shapes that vary per row; this is eight stable fields known at design time.
2. **Duplicating document identity onto every chunk.** "warfarin" written into ~200 rows
   per document, with no answer to "what if one row disagrees?". The split makes
   disagreement impossible by construction.

**Cost accepted:** adding a metadata field later is an `ALTER TABLE` migration rather
than a new JSON key — seconds of work at this corpus size.

---

## messages.sources: the citation mapping is frozen onto each assistant message

**Timestamp:** 2026-08-12 05:11 -07:00

**Decision:** when the assistant's answer is persisted (once, at stream `done`), the
per-request tag→citation mapping is persisted with it in the same row
(`messages.sources jsonb`). Loading a conversation returns each message with its own
frozen mapping; the client renders `[[Sn]]` tags from it exactly as it did live.

**Why:** history is shared and global. A later reader never received the original SSE
`sources` event; without a stored mapping, saved answers render with dead `[[S1]]` tags —
and citations are the graded behavior. The snapshot also survives re-ingestion: the
reconciliation design deletes orphaned chunks, so an answer must record what it actually
cited at the time, not point at rows that may be gone or changed.

**Rejected, with reasons:**

1. **Storing chunk IDs and re-resolving citations on load.** Breaks under
   re-ingestion — deleted chunks produce broken citations; changed chunks silently swap
   in content the answer was never grounded in.
2. **Typed columns for the mapping (consistency with the schema decision).** Not
   inconsistent — the same rule applied: chunk metadata is filtered on, so it is typed;
   the mapping is a write-once snapshot read whole, never queried inside, so it is
   `jsonb`.

**Cost accepted:** a few KB of duplicated citation data per assistant message.

---

## trace=true skips the conversation-history write

**Timestamp:** 2026-08-12 05:11 -07:00

**Decision:** in trace mode the full pipeline runs — gate, retrieval, fusion, rerank,
generation — but nothing is written to `conversations`/`messages`. The eval harness
therefore leaves no residue in the shared UI.

**Why:** a full eval run is ~18 prompts × 3 retrieval modes × rerank on/off ≈ 100+
requests, run repeatedly while tuning. With no auth and no ownership there is no cleanup
mechanism; the shared history — the first thing a grader opens — would be a landfill of
robot conversations. Persistence happens after the answer exists, so skipping it changes
nothing about what the eval measures.

**Rejected:** letting the harness write history (indefensible junk in the graded UI);
pointing the harness at a separate database (a second environment to keep schema-synced,
and the eval would no longer run against the deployed data).

**Cost accepted, stated honestly:** the history-write code path is not exercised by the
eval harness; it is covered by a hermetic unit test on the persistence logic instead.

---

## TRAZAMINE replaced by a standard PLR trazodone label

**Timestamp:** 2026-08-12 06:57 -07:00 (user swapped the file earlier this session; recorded now)

**Decision:** `Trazodone.pdf` is now the Aurolife Pharma trazodone hydrochloride tablet
label — a modern PLR document (HIGHLIGHTS present, full numbered sections 1–17,
34 pages). The TRAZAMINE co-packaged "Physician Therapeutics" product is out of the
corpus entirely.

**Why:** TRAZAMINE was the corpus's only trazodone document, so every trazodone question
would have been answered from a fringe co-packaged product with thin clinical content
and idiosyncratic headings, cited under an unfamiliar brand name.

**Rejected:**

1. **Keeping TRAZAMINE as the only trazodone document** — a common drug answered from a
   non-standard label was the weakest option.
2. **Replace-and-keep (24-document corpus)** — the recommended option; it would have
   kept TRAZAMINE as a named hard case for the quirk-handling story. The user chose the
   clean swap; the old-format Albuterol and OTC Aspirin documents still carry the
   hard-case role.

**Consequence:** the corpus is now 19 PLR / 2 old-format / 2 OTC. Q6(e) is resolved;
Q6(a)–(d) (carving fallback, HIGHLIGHTS/TOC exclusion, multi-active identity, packaging
sections) remain open.

---

## Page is the guaranteed citation floor — NOT NULL, never a fallback tier

**Timestamp:** 2026-08-12 07:12 -07:00

**Decision:** `page_start`/`page_end` are `NOT NULL` on every chunk. Document + page is
the guaranteed floor of every citation and every served chunk deep-links to its page via
`#page=`. The citation ladder has exactly two tiers — document + section + page, or
document + page — and only the *section* tier degrades. A chunk whose pages cannot be
resolved at ingestion is a loud ingestion error, not a chunk with a weaker citation.

**What this supersedes:** the 04:28 ladder ended with a theoretical third tier
("document only, if even the page is unknown") and the DDL left the page columns
implicitly nullable. That escape hatch is removed: pages come from Unstructured's
per-element `page_number`, which every element of a successfully extracted PDF has, so a
missing page signals a broken extraction that must fail the document — silently
degrading the citation would hide the failure the pipeline is supposed to surface.

**Why:** the user set this explicitly — deep linking is a core behavior of how chunks
are served to the frontend, not garnish on good chunks. A guaranteed page also keeps
the eval's grounding checks simple: every citation in every answer is verifiable to a
page, no special cases.

---

## PLR-only corpus: 19 uniform modern labels, one carving strategy

**Timestamp:** 2026-08-12 07:16 -07:00

**Decision:** the corpus is the 19-document PLR-only set on the `plr-corpus` branch
(commit `8484632`) — 11 drugs, every document programmatically verified as PLR
(HIGHLIGHTS present, 15–17 numbered top-level sections). The old-format Albuterol
labels (2) and OTC Drug Facts Aspirin labels (2) are out. This supersedes the
2026-08-12 03:25 position that kept them as deliberate hard cases.

**Why:** one carving strategy covers 19/19 documents — the tiered heading-vocabulary
fallback (Q6a) never gets built, which removes the most fragile, hardest-to-defend part
of ingestion. Citations become structurally uniform (every chunk can carry a numbered
section), and the corpus story is one sentence: "every document is the same regulated
format; here is how we verified that."

**Rejected, with reasons:**

1. **The mixed 23-doc corpus with hard cases** (the previous position). Old-format and
   OTC handling made a richer "quirks handled deliberately" story, but each extra
   document class bought a heading-vocabulary tier that exists only to serve 2
   documents — high defense burden per document served.
2. **Keeping aspirin at any cost.** Plain aspirin has no PLR label (it is an OTC
   monograph drug — no modern prescribing information exists), so keeping the drug
   meant keeping the Drug Facts class. Cut instead; aspirin and albuterol become
   clean unanswerable eval questions.

**Quirk findings from verification, kept on the record:** two heading-numbering
variants (`5 WARNINGS` vs Warfarin_2/3's `5.  WARNINGS` trailing dot); ALL-CAPS
top-level headings vs Title Case subsections (`5.1 Hemorrhage`) — the single carving
pattern must accept all four combinations, and the hermetic carving tests cover them.

**Remaining quirk surface (the honest version for the graded doc):** cross-page tables,
HIGHLIGHTS/TOC self-duplication, ezetimibe+simvastatin multi-active combos, same-drug
multi-labeler near-duplicates (3 warfarins), and packaging sections. Q6 shrinks to
b/c/d: HIGHLIGHTS/TOC exclusion, `actives[]`, packaging-section exclusion.

**Repo state note:** `main`'s working tree still holds the pre-decision mixed corpus
plus 11 uncommitted OTC downloads; cleanup pending (merge or re-commit when the user
says so).

---

## CI runs on pull requests, both jobs unconditionally

**Timestamp:** 2026-08-12 06:41 -07:00

**Decision:** the CI workflow triggers on `pull_request` (every PR) plus `push` to
`main` (merge verification), replacing the original bare `on: push`. A second `frontend`
job (npm ci → eslint → tsc -b → vite build) joins the backend job (uv sync → ruff →
mypy → pytest). Both jobs run on every PR regardless of which paths it touches.

**Why:** bare `on: push` ran CI on every branch push but attached no check to the PR
itself, so a PR could merge unverified. PR-level checks are the gate that matters in a
PR-based flow; push-to-main keeps the merged result verified too.

**Rejected:** path-filtered per-side workflows (a backend-only PR skipping the frontend
job). Native `paths:` filters interact badly with required status checks — a skipped
workflow reports no status and can leave a PR pending forever, or worse, mergeable
without the check. Both jobs together cost ~1 minute, so the savings do not justify the
footgun at this repo size. Also rejected: dependency caching in CI (setup-node/uv
caches) — marginal minutes saved, more configuration to defend.

**Cost accepted:** docs-only PRs still run both jobs (~1 min of free-tier runner time).

---

## Schema management: versioned plain-SQL migrations with a small psycopg runner

**Timestamp:** 2026-08-12 07:16 -07:00

**Decision:** the storage schema ships as ordered plain-SQL files in
`backend/persistence/migrations/` — starting with `0001_initial_schema.sql`, which is the
DESIGN.md schema verbatim (`documents`, `chunks` with `vector(1536)` + generated `tsv` +
HNSW + GIN, `conversations`, `messages`, plus an index on
`messages (conversation_id, created_at)` since Postgres does not index FKs
automatically). A ~50-line typed runner (`python -m persistence.migrate`) applies pending
files in filename order over an autocommit psycopg connection, one transaction per file
(the DDL plus a row in `schema_migrations`), and refuses to run when an applied migration
is missing from disk — that is drift, not progress. The pending-file diff is a pure
function with hermetic tests; the runner itself is a thin adapter, per the logic/adapter
split. `psycopg[binary]` joins the backend dependencies — it is also the driver the
retrieval SQL (HNSW + `ts_rank` legs) will need, so it earns its place twice.

**Rejected, with reasons:**

1. **Alembic + SQLAlchemy.** The backend has no ORM and would be adopting one only to
   version DDL; pgvector HNSW options and generated `tsvector` columns end up as raw-SQL
   escape hatches inside Alembic's Python DSL anyway — a framework wrapping the same SQL
   with more indirection and less readability.
2. **Supabase CLI migrations.** Adds a non-Python tool to the toolchain and ties schema
   history to vendor tooling. Supabase is deliberately used as hosted Postgres + Storage
   and nothing more; CI and the hermetic tests could not exercise any of it.
3. **A single `schema.sql` with no version tracking.** Not updatable: once any column
   addition lands (the interview pre-announces a live modification), there is no way to
   tell a fresh database from a stale one. The tracking table costs ~15 lines and buys
   idempotent re-runs.

**Cost accepted:** no down-migrations and no checksum verification of applied files — at
demo scale, rolling forward or resetting the database is cheaper than maintaining both
directions. Also one `# type: ignore[call-arg]` inside `config.load_settings()`: strict
mypy reads pydantic-settings fields as required constructor arguments even though they
load from the environment; the shared factory confines the documented workaround to a
single line all callers reuse.

---

## Simvastatin combos dropped — corpus is 17 docs, 10 drugs, all single-active

**Timestamp:** 2026-08-12 07:33 -07:00

**Decision:** both ezetimibe+simvastatin documents are removed (`plr-corpus` commit
`fa9b022`). Every remaining document has exactly one active ingredient, so `documents`
keeps a single `drug_name` column — the `display_name` + `actives text[]` machinery
proposed for combos (Q6c) is never built. Simvastatin joins albuterol and aspirin as
out-of-corpus drugs for unanswerable eval questions.

**Why:** the two combo labels were the only reason for multi-active identity handling.
Cutting 2 of 19 documents deletes an entire metadata concept (array column, array-aware
filtering, combo-aware eval ground truth) — the same trade as the PLR-only decision:
corpus uniformity purchased with documents to spare above the 15-doc floor.

**Rejected:**

1. **Keeping the combos with `actives text[]`.** Workable and already designed, but it
   existed to serve 2 documents, and "simvastatin" questions would always have carried
   the awkwardness of citing an ezetimibe-containing product.
2. **Replacing them with a plain simvastatin label.** Would keep the drug at zero combo
   cost — rejected because 17 docs / 10 drugs already clears the corpus floor
   comfortably, and an out-of-corpus statin is more useful to the eval suite than an
   eleventh in-corpus drug.

**Consequence:** corpus floor margin is now 2 documents (17 vs the required 15). Any
further cuts must come with replacements.

---

## Front-stage rewriter defined: contextualize + normalize, one string for both legs

**Timestamp:** 2026-08-12 07:34 -07:00

**Decision:** the query rewrite does two things in one output: resolve pronouns and
follow-up references against the conversation history so the query stands alone, and
normalize terminology — brand → generic drug names (Coumadin → warfarin), abbreviations
expanded. The single rewritten string feeds both the dense and sparse legs.

**Why:** the corpus is generic-name regulatory prose. A brand-name query can miss the
sparse leg entirely (`ts_rank` has no synonym awareness) and lands weaker on dense —
normalization is the highest-payoff rewrite for this corpus and makes a clean eval
delta.

**Rejected, with reasons:**

1. **Contextualize only.** Leaves brand-name and abbreviated queries stranded on the
   sparse leg.
2. **Also expand with synonyms/related terms.** Recall boost not worth the precision
   pollution on a corpus of near-identical sibling labels (3 warfarins, 2 apixabans) —
   expansion terms match every sibling equally.

---

## Gate and rewrite toggle independently; both off skips the front stage — supersedes "the rewrite is optional, the gate is not" (04:17)

**Timestamp:** 2026-08-12 07:34 -07:00

**Decision (user's call, overriding the recorded design):** the front stage's two jobs
toggle independently as request parameters. `gate` and `rewrite` each add their section
of the prompt and their field of the response schema; both, either, or neither can run.
With both off the LLM call is skipped entirely and the raw query proceeds. In-app
traffic runs with both on — the toggles exist for eval deltas. This replaces the 04:17
entry's "gating always executes" and DESIGN.md's "gating variant" wording.

**Why:** each behavior's delta becomes separately measurable by the harness — gate
on/off over the personal-advice questions, rewrite on/off over retrieval metrics — with
no confound between them.

**Rejected, with reasons:**

1. **Mandatory gate + optional rewrite** (the 04:17 design). Simpler safety story, but
   the harness could never show the gate's own before/after.
2. **A single gate-on/off toggle beside the rewrite toggle, one combined prompt** (the
   AI's recommendation). Coarser: prompt sections would not track the toggles, so
   neither behavior could be isolated cleanly.

---

## Gate scope: personal medical advice only, one binary flag

**Timestamp:** 2026-08-12 07:34 -07:00

**Decision:** the gate decides exactly one thing — does the question seek personal
medical advice. No emergency class, no off-topic class.

**Why:** the flag matches the graded refusal behavior 1:1. Off-topic questions flow
through retrieval and land in the honest "not in the corpus" path, which is its own
graded behavior.

**Rejected:** an emergency-symptoms class with its own canned response (defensible
medical posture, ungraded surface); an off-topic deflection class (saves pennies of
retrieval, adds refusal text and test surface).

---

## Front stage fails closed

**Timestamp:** 2026-08-12 07:34 -07:00

**Decision (user's call, against the AI's recommendation):** when the front-stage call
fails — API error, timeout, unparseable response — the query is refused with a distinct
canned "can't process this right now" message, not answered ungated and not surfaced as
a raw API error. No retry.

**Why:** the gate is a graded safety behavior; its failure direction should be the safe
one.

**Rejected, with reasons:**

1. **Typed API error to the client** (the AI's recommendation — outages should look
   like outages). Honest, but it makes gate availability a precondition the safety
   behavior silently depends on.
2. **Fail open.** The graded safety behavior degrades exactly when the system is flaky.

**Cost accepted:** a front-stage outage masquerades as a refusal; the distinct message
text keeps it distinguishable from the medical-advice refusal.

---

## Front-stage adapter calls the OpenAI SDK directly, not LangChain

**Timestamp:** 2026-08-12 07:34 -07:00

**Decision:** `run_front_stage` uses the OpenAI SDK's structured-output parse
(`client.chat.completions.parse` with a pydantic schema per toggle combination)
directly, in `backend/retrieval/tools/front_stage.py`. `langchain-openai` is not added
for this one call; LangChain remains the composition layer for generation (`chat/`).

**Why:** `openai` is already a dependency and its parse API returns the typed verdict
with zero glue. A partner package for a single non-streaming call is dependency surface
with no payoff.

**Rejected:** `langchain-openai` + `with_structured_output` for stack uniformity —
uniformity with generation code that does not exist yet is not a benefit. Revisit if
the generation chain wants to share model clients.

---

## Prompts and canned messages: one per file in dedicated packages

**Timestamp:** 2026-08-12 08:40 -07:00

**Decision (user's call, correcting the AI's layout):** prompt texts live in
`backend/prompts/` and canned user-facing messages in `backend/messages/` — one
constant per module, re-exported through each package's `__init__.py` so call sites
import from the package index (`from prompts import FRONT_STAGE_GATE`). The front
stage's three prompt pieces and two canned responses moved there; every later
prompt-bearing stage (generation, reranker) and canned response follows the same
convention. Both packages joined the strict-mypy file list.

**Why:** prompts and refusal texts are content artifacts, not logic — they get read,
reviewed, and edited on their own terms. One-per-file keeps each individually
diffable and findable without touching the code that assembles them.

**Rejected:**

1. **Module-level constants inline beside their logic** (the AI's initial form in
   `front_stage.py`). Fine at three prompts; scales into prompt text interleaved with
   pipeline code as generation and reranker prompts arrive.
2. **A single catalog module per kind** (`prompts.py`, `messages.py`). Fewer files,
   but every prompt edit diffs against one growing file and the index import pattern
   is lost.

---

## Schema↔type association: hand-written row models plus a live schema check

**Timestamp:** 2026-08-12 08:54 -07:00

**Decision:** each table gets one hand-written Pydantic row model
(`persistence/rows.py`) carrying only the columns the app reads — `chunks.embedding`
and `tsv` are omitted because no code path reads them back. Adapters validate every row
they read into these models (the typed-adapter-boundary pattern DESIGN.md already
committed to), so mypy checks every function that touches row data, and live drift
becomes a typed validation error instead of silent garbage. Structure verification is a
live health check, not a CI test: `python -m healthcheck` compares each model's fields
against `information_schema.columns` (presence, type, nullability) on the real database.
The comparison is a pure function with hermetic tests; only the `information_schema`
read touches the network.

**Rejected, with reasons:**

1. **SQLAlchemy models as single source of truth (ORM + Alembic autogenerate).** The
   ORM's payoff scales with entity count, team size, object-graph traversal, and schema
   churn — this project has four tables, one developer, no graph traversal, and 2–4
   migrations ever. The load-bearing queries (HNSW cosine, `websearch_to_tsquery` +
   `ts_rank`, RRF fusion) stay raw SQL under an ORM anyway, so single-sourcing would
   govern only the boring CRUD. Alembic autogenerate is least reliable on exactly this
   schema (custom `vector` type rendering, generated columns, check constraints), so
   every generated migration needs hand review regardless. *Correction to the 07:16
   entry:* pgvector columns and generated `tsvector` **are** expressible in SQLAlchemy
   DDL (`pgvector.sqlalchemy`, `Computed`) — the earlier "escape hatch" claim overstated
   that; the real costs are the ones above.
2. **Codegen from the schema (sqlc, sqlacodegen).** Adds a generation step to the
   toolchain; the Python codegen options are the weakest of that family; four small
   models do not justify it.
3. **Schema tests against an ephemeral Postgres (testcontainers / CI service
   container).** The industry-standard migration test, but it expands CI beyond the
   mandated lint + type check + hermetic tests and adds a Docker dependency. Deferred
   unless explicitly wanted; the live health check covers the failure mode that
   actually matters here (deployed schema drifting from code).

**Cost accepted:** the check is a subset check — columns no model reads (`embedding`,
`tsv`) are unverified, and constraints/indexes are not compared, only columns. The
models can drift from the DDL between health-check runs; runtime boundary validation is
the backstop.

---

## Gate and rewriter split into two self-contained tools with individual LLM calls — supersedes the combined front-stage call (04:28, 07:34)

**Timestamp:** 2026-08-12 08:56 -07:00

**Decision (user's call, restructuring the built version):** the gate and the rewriter
are two separate tools in `retrieval/tools/` — `advice_gate.py` and
`query_rewriter.py` — each with its own prompt file, its own response schema, and its
own `gpt-5-mini` structured-output call. The pipeline is where they come together:
`retrieval/pipeline.py` gains `prepare_query()`, which runs the gate (stop on refusal)
then the rewriter, each behind its own toggle; both off means no LLM call. The
positional name `front_stage` is gone — tools are named for what they do, not where
they sit. Shared history-transcript rendering moved to `retrieval/tools/history.py`.

**Per-tool failure semantics the combined call could not express:** the gate still
fails closed (refuse on error — safety), but the rewriter now **fails open**, falling
back to the raw query — rewriting is an optimization, and refusing a question because
the rewriter broke was the wrong direction. The fail-closed message is accordingly
`GATE_UNAVAILABLE`, owned by the gate.

**Cost accepted:** two LLM calls per fully-enabled query instead of one — added
latency (sequential today) and roughly double the per-query front-stage spend. Noted
future tweak: run the two calls concurrently to restore one-call wall-clock, discarding
the rewrite on a refusal.

**Rejected, with reasons:**

1. **The combined single-call module** (the built `front_stage.py`). One call cheaper,
   but the module was itself the composition point — toggles selected prompt sections
   and merged schemas inside it — duplicating the pipeline's job, under a name that
   described position rather than behavior.
2. **Logic-only tools sharing one call assembled by the pipeline** (Plan B — briefly
   selected, reversed in the same session). Keeps the one-call cost but the tools
   cannot run independently, and the merged both-enabled schema has to live somewhere
   neither tool owns.

---

## Ingestion exclusion list: TOC, HIGHLIGHTS, and packaging sections are not indexed

**Timestamp:** 2026-08-12 09:58 -07:00

**Decision:** Pass 1 carving drops three kinds of content before anything is chunked or
embedded — the table-of-contents pages, the `HIGHLIGHTS OF PRESCRIBING INFORMATION`
block, and the packaging sections (`PRINCIPAL DISPLAY PANEL` / `PACKAGE LABEL` variants,
`INGREDIENTS AND APPEARANCE`). All three exist in all 17 documents, so the rule is
uniform — one exclusion list, no per-document cases.

**Why each:**

1. **TOC** — content-free keyword bait: it contains every section title of the document
   and no answers, so sparse search ranks it for almost any query, wasting candidate
   slots.
2. **HIGHLIGHTS** — a terse restatement of sections already indexed in full. Kept, it
   makes every key fact exist twice (boxed warning: three times), splits RRF
   contributions across near-duplicates, crowds the top-5 context window that multi-doc
   synthesis questions need, and lets the model cite the summary instead of the
   authoritative section.
3. **Packaging sections** — carton copy ("SATISFACTION GUARANTEED"), NDC barcodes, and
   UNII ingredient tables are dense with distinctive exact tokens that `ts_rank` scores
   highly; a strength-mention query can rank a carton panel above the dosage section,
   and a citation pointing at carton text is indefensible.

**Rejected, with reasons:**

1. **Indexing HIGHLIGHTS as a tagged, down-weighted chunk type.** Preserves its terse
   phrasing (which sometimes matches terse queries better) but introduces a weighting
   tunable that would itself need eval justification. The one-sentence exclusion is the
   defensible version.
2. **Keeping packaging sections for inactive-ingredient coverage.** Real loss — "does
   this contain gelatin?" becomes unanswerable — accepted as a deliberate scope line and
   recycled as unanswerable-question eval material.

**Consequence:** ingestion is now 100% specified. With this, every design decision on
the open list is settled; remaining work is authoring (eval suite, prompt wordings) and
implementation constants.

---

## Retrieval config: one object carrying every switch, and one pipeline entry point

**Timestamp:** 2026-08-12 10:42 -07:00

**Decision:** a single frozen `RetrievalConfig` in `retrieval/config.py` holds all four
switches (`mode`, `gate`, `rewrite`, `rerank`) and all four cut-offs
(`candidate_limit=40`, `rrf_k=60`, `fused_limit=20`, `final_limit=8`). Every pipeline
function takes it as an argument. `pipeline.run_retrieval()` is the single entry point
for callers: gate → rewrite → embed → dense + sparse → fuse → rerank → cut, returning
`Refusal | Retrieved`.

**Why one object:** the front-stage toggles and the retrieval switches are the same kind
of thing — request parameters the eval harness varies one at a time. Two shapes would
have forced the query endpoint to assemble settings from two places and the harness to
sweep two axes with different mechanics. The cost is real and was accepted: it changed
`prepare_query`'s existing signature from `gate=`/`rewrite=` keyword booleans to a config
argument, which is a breaking change for any caller written against the previous commit.

**Why one entry point:** `CLAUDE.md` puts composition only in `pipeline.py`. A two-call
API (`prepare_query` then `retrieve`) would have handed step ordering to the streaming
code in `chat/`. The refusal branch stays legible because it is a distinct return type,
not a flag — callers handle exactly two outcomes.

**Rejected:** keeping gate/rewrite as booleans beside a retrieval-only config (nothing
existing breaks, but settings arrive in two shapes); and returning a bare
`list[ScoredChunk]` from `run_retrieval` (loses the rewritten query, which the eval trace
needs to explain why a retrieval succeeded or failed).

**Return contract:** `Retrieved` = the query actually searched + `list[ScoredChunk]`, each
chunk carrying its dense rank, sparse rank, RRF score, and rerank score. The alternative —
also returning the intermediate 40/40/20 candidate lists — was rejected as heavier for
`chat/` to consume than its eval value justifies at this corpus size. It is a cheap change
later if failure analysis needs to separate "never retrieved" from "retrieved then
reranked away"; the per-stage ranks already on each survivor answer most of that.

---

## Retrieval legs run sequentially — supersedes "in parallel" (2026-08-12 09:58)

**Timestamp:** 2026-08-12 10:42 -07:00

**Decision:** the dense and sparse searches run one after the other on a single
connection. The earlier design text said they "run in parallel over the same chunk
table"; that was an unexamined assumption and is now corrected.

**Why:** concurrency here needs either a second database connection or a thread pool, and
buys one query's latency (tens of milliseconds against a 17-document table) inside a
request that already spends two LLM round trips on the gate and rewriter and a third on
the reranker. `CLAUDE.md` lists performance work as something not to build unasked.

**Known limit, not hidden:** at 10,000 documents this ordering stops being free and the
two legs become a genuine parallelism candidate — it belongs in the scaling section, not
in the demo.

---

## Reranker robustness: all-or-nothing scoring, stable sort, no temperature

**Timestamp:** 2026-08-12 10:42 -07:00

**Decision:** three rules govern the reranker's output handling.

1. **All-or-nothing.** The response must score every candidate number exactly once. A
   response that misses one, repeats one, or invents a number is discarded whole and the
   fused RRF order stands. Rejected alternative: applying partial scores and sorting the
   unscored candidates to the bottom — that invents a policy for a case the model should
   never produce, and silently demotes chunks the model simply forgot to mention.
2. **Stable sort.** Python's sort is stable, so equal reranker scores keep RRF order for
   free. This is why the design's "ties fall back to RRF order" needs no tie-break code.
3. **No temperature.** The design previously specified temperature 0. The gpt-5 family
   accepts only its default temperature, so the parameter is omitted. Determinism comes
   from the sort living in code rather than from the sampler — which was the point of
   scoring-then-sorting rather than asking the model to return a ranked list.

**Also decided:** candidates are labeled 1..N in the prompt rather than by database id.
Small integers are easier for the model to echo back correctly, and a mis-copied database
id would silently attach a score to the wrong chunk, whereas a bad position number fails
the all-or-nothing check.

---

## Embedding model and width are code constants, not environment variables

**Timestamp:** 2026-08-12 10:42 -07:00

**Decision:** `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` live in `backend/config.py` as
plain module constants, imported by both `retrieval/tools/embedder.py` and ingestion.
`config.py` — the file that otherwise holds environment-backed settings — was chosen for
discoverability: the embedding configuration is a project-wide fact, and burying it in
one tool module makes it something a reader has to hunt for.

**Rejected — putting them in `.env`:** proposed for project-wide visibility, rejected
because the value is not environment-tunable in any real sense. The width is already
frozen into the schema as `vector(1536)`, and every stored vector was produced by one
specific model; changing the value would not reconfigure the app, it would break it, and
fixing it means re-embedding the whole corpus behind a migration. Worse, `.env` files
differ per machine by nature, so an env var would reintroduce exactly the drift a single
definition exists to prevent — silently, between a laptop and production.

**Rejected — a query-only embedder with ingestion writing its own:** avoids a cross-
package import but defines the model name and dimension count twice. Drift between them
does not raise; it degrades retrieval quality in a way that looks like a bad answer, not
like a bug. Both packages already import `config`, so the shared constant costs no new
coupling.

---

## LangChain's scope: one rule — `ChatOpenAI` is the model client for every LLM call

**Timestamp:** 2026-08-12 11:12 -07:00

**Decision (user's call, against the AI's recommendation):** `langchain-openai`'s
`ChatOpenAI` is the model client for all four LLM call sites — generation, advice gate,
query rewriter, reranker. One rule, no per-call-site exceptions. Generation is built this
way; the gate and rewriter are pending retrofit (recorded as debt in `DESIGN.md`).

**What prompted the question:** the backend had `langchain` declared as a dependency and
imported it in zero files. An audit of what remains to build found exactly one LangChain
component with a genuine case — `RecursiveCharacterTextSplitter` for pass-2 chunking —
and that ships in `langchain-text-splitters`, which was not in the lock file either. Two
further findings: `langchain` is pinned at 1.3.15, whose dependency list is
`langchain-core` + **`langgraph`** + `pydantic` (LangChain 1.x is an agent framework; the
classic chains moved to `langchain-classic`), so the lean backend container was carrying
langgraph, langgraph-checkpoint/prebuilt/sdk, langsmith, orjson, websockets and xxhash for
nothing. And `langchain-openai` was absent, so any LangChain LLM call needed it added.

**Rejected, with reasons:**

1. **Splitter only; OpenAI SDK for every LLM call (the AI's recommendation).** The tighter
   engineering answer at four call sites and one provider: `ChatOpenAI`'s selling points
   here are provider swappability (locked to OpenAI — the cross-provider judge was already
   rejected on cost) and retry/callback hooks (both on the do-not-build list). The user
   chose uniformity instead: "why LangChain here and not there?" is a worse question to
   field in the follow-up interview than "why LangChain at all?", which the scope note in
   `DESIGN.md` answers in one paragraph.
2. **LangChain for generation only, SDK for the structured-output tools.** A defensible
   split on paper — streaming chain versus one-shot typed calls — but it leaves two idioms
   in one backend and makes the boundary between them the thing that gets asked about.
3. **Dropping `langchain` entirely.** Rejected with (1); it would also have meant
   correcting the stack table rather than making it true.

**Cost accepted, stated honestly:** LangChain's retrievers, `PGVector` store, and
document loaders stay unused — `PGVector` keeps metadata in a JSONB blob that the
typed-column schema rejected outright, and `UnstructuredPDFLoader` flattens away the
per-element `page_number` and table HTML that carving and the page floor depend on. So the
project uses LangChain as a model client and a text splitter, and nothing else. That is a
narrow slice of the library, and `DESIGN.md` says so rather than implying broader use.

**Consequence for typing:** `ChatOpenAI.astream` yields `AIMessageChunk`, whose `.content`
is typed `str | list[str | dict]` (LangChain 1.x standard content blocks). Token text
comes off `.text`, which returns a `TextAccessor` — verified to subclass `str`, so it
flows into a `str` field without a cast. `api_key` needed wrapping in `SecretStr`.

---

## Generation takes no conversation history; the rewriter is what makes a follow-up standalone

**Timestamp:** 2026-08-12 11:12 -07:00

**Decision:** the generation prompt receives the standalone question and the tagged
excerpts, and nothing else. Conversation history is never placed in the generation context
window.

**Why:** grounding is graded on the model answering *only* from retrieved labeling. Prior
assistant turns are ungrounded text; putting them beside the excerpts gives "answer only
from the provided chunks" a competing source, and a hallucination sourced from an earlier
turn presents exactly as a grounding failure. The query rewriter already exists to resolve
pronouns and follow-up references against history, so the standalone query is the seam
where history has already been consumed.

**Rejected — chunks + history + query:** follow-ups would still resolve with `rewrite`
toggled off, and the model could match the conversation's register. Rejected because it
buys register at the cost of the behavior carrying 30% of the rubric.

**Cost accepted:** with `rewrite` off, a follow-up loses its referent and retrieval sees a
context-free query. That is not a regression to fix — it is precisely the before/after
delta the rewrite toggle exists to measure, and the eval harness reads it as such.

---

## Empty retrieval short-circuits to a canned message rather than a generation call

**Timestamp:** 2026-08-12 11:12 -07:00

**Decision:** when retrieval hands generation zero chunks, `chat/` streams
`NO_SUPPORTING_CONTEXT` — `sources` with an empty mapping, one `token`, `done` — and makes
no model call. It shares one canned-response helper with the upstream gate refusal, so
every pre-written answer reaches the client through the identical event contract.

**Why:** the response is deterministic and hermetically testable, it spends nothing to say
"I found nothing", and it is the natural landing spot for the relevance threshold the
assignment pre-announces as a live interview modification — filtering to zero produces the
decline path with no extra branch. Note that with hybrid retrieval and no threshold, top-k
nearly always returns *something*, so this path is mostly latent today; the honest
not-in-corpus behavior on a populated-but-irrelevant chunk set is the prompt's job, not
this branch's.

**Rejected — always call the model and let the prompt refuse:** one code path, and the
honest-refusal behavior would live entirely in the graded prompt. Rejected because it
spends an LLM call to state the obvious and makes the refusal wording non-deterministic in
the exact case the graders test deliberately.

---

## `chat/` takes chunks through a Protocol-gated interface, not the row models whole

**Timestamp:** 2026-08-12 11:12 -07:00

**Decision (user's call):** `chat.context.RetrievedChunk` is a frozen dataclass carrying a
`ChunkRow` and a `document: CitedDocument`, where `CitedDocument` is a `typing.Protocol`
declaring exactly `id: str` and `drug_name: str`. `DocumentRow` satisfies it structurally
without knowing it exists. Verified: reading `retrieved.document.ingested_at` inside
`chat/` is a mypy `attr-defined` error, while passing a `DocumentRow` in type-checks
cleanly.

**Why a gate at all:** `chat/` consumes 7 fields; the two row models carry 18. The user
asked for the row models to remain the reference while the unneeded fields were excluded
from what `chat/` can see.

**What was not possible, and why:** a field-*excluding* subclass. Inheritance adds members
and cannot remove them, and substitutability forces the direction — for a `DocumentRow` to
be usable where a `CitedDocument` is expected, the narrower type has to be the base. So
"`DocumentRow` as base, `CitedDocument` excludes fields from it" is the one arrangement
the type system will not express, whatever the class body says.

**Rejected, with reasons:**

1. **A flat model re-declaring the 7 fields.** The most self-documenting seam and the
   lightest fixtures — rejected because the field list would then exist twice, and only
   the `rows.py` copy is checked against the live schema by `python -m healthcheck`. A
   renamed column would keep compiling and quietly mean something else.
2. **A narrow base class in `rows.py` that `DocumentRow` extends.** Declares each field
   exactly once with no new typing concept, and was verified compatible with the health
   check (`model_fields` includes inherited fields). Rejected on coordination: it edits a
   file the retrieval and ingestion sessions are working in.
3. **A projection model with `.of(DocumentRow)` plus a hermetic drift test.** Closest to
   the "derive it from `DocumentRow`" framing, and it yields a real value object. Rejected
   because it catches a rename at runtime and in CI, where the Protocol catches it at the
   type check.
4. **Carrying `ChunkRow` + `DocumentRow` whole with no gate.** Simplest seam; the leak
   surface is already closed by the `Citation` model on the way out. Rejected for the
   18-field fixtures and the absence of any mechanism against a later edit reading
   `ingested_at`.

**Correction recorded:** the AI first argued the pair put document internals "in reach of
prompt-assembly code" as if that were a leak risk. It is not — what escapes is bounded by
the `Citation` model and by explicit reads, so input gating buys tidiness and blast
radius, not leak prevention.

---

## Citations carry no manufacturer; same-drug ambiguity is accepted

**Timestamp:** 2026-08-12 11:12 -07:00

**Decision (user's call, against the AI's recommendation):** a citation is `document_id` +
`drug` + `section_number` + `section_title` + `page_start`. `manufacturer` and
`formulation` are not carried.

**The ambiguity being accepted, stated plainly:** 13 of the 17 documents belong to a drug
that has more than one label in the corpus — apixaban (2), bupropion (2), digoxin (2),
escitalopram (2), venlafaxine (2), warfarin (3). An answer synthesizing across the three
warfarin labels emits three citations that all render as warfarin plus the same section,
and a reader cannot tell them apart on the label alone. The look-alike discrimination the
hybrid retrieval stretch goal exists to do is therefore measurable in the eval trace and
invisible in the UI.

**Why it is nonetheless fine:** `document_id` is in the payload and is filename-derived,
so click-through resolves to the correct PDF at the correct page, and the frontend can
disambiguate on it if it chooses. Nothing is functionally broken; the cost is a rendered
label that is less specific than the underlying data.

**Rejected — carrying `manufacturer` (+ `formulation`), the AI's recommendation:** it
would render the labeler alongside the drug and, where two labels of one drug differ by
formulation, distinguish bupropion SR from bupropion XL — clinically the more meaningful
of the two. Cost was one or two string fields on the seam, the sources payload, and every
frozen `messages.sources` snapshot. The user chose the smaller payload and the `DESIGN.md`
citation shape as already specified. Revisit if the ambiguity reads badly once the UI is
real.

---

## Retrieval switches: dense always on, sparse and rerank as toggles — supersedes the three-valued `mode` (10:42)

**Timestamp:** 2026-08-12 11:24 -07:00

**Decision:** `RetrievalConfig` drops the `mode` field (`hybrid` / `dense` / `sparse`).
Dense vector search always runs, and `sparse` joins `rerank`, `gate`, and `rewrite` as a
plain independent boolean. Sparse on means the reranker sees the RRF-fused union of both
legs; sparse off means it sees the dense candidates alone. The reranker's contract is
identical either way: candidates in, the same candidates out, reordered.

**Why:** the three-valued mode modeled the two legs as symmetric alternatives, which
misdescribes the system. Dense search is the retrieval this app would have with no
stretch goal at all; the keyword leg is an additive candidate source layered on top. The
toggle shape says that out loud, and it makes all four switches the same kind of thing —
one uniform axis for the eval harness and one uniform mapping from request parameters.

**What it costs:** sparse-only is no longer expressible. Accepted deliberately — it is a
diagnostic configuration, not a shippable one, and the diagnostic need is already met
because every surviving `ScoredChunk` records its `sparse_rank`, so what the keyword leg
contributed stays visible in any run where it is on.

**Consequence for the eval harness:** the retrieval sweep becomes dense → dense+sparse →
each with the reranker, rather than `hybrid` vs `dense` vs `sparse`. This is the better
framing of the stretch goal's required before/after delta anyway: it measures what hybrid
retrieval *adds*, which is the claim being graded.

**Code effect:** `dense_candidates()` disappeared from `pipeline.py` — with no condition
left to express, it was a one-line wrapper — and the dense search is called directly in
`retrieve_chunks()`. `sparse_candidates()` keeps its guard. The asymmetry in the code now
mirrors the real asymmetry in the design.

---

## Reranker and embedder move onto `langchain-openai` — supersedes the raw-SDK reranker (10:42)

**Timestamp:** 2026-08-12 11:41 -07:00

**Decision:** the reranker is built as
`ChatOpenAI(model="gpt-5-nano").with_structured_output(RerankScores)`, and the embedder is
`OpenAIEmbeddings(model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS)`. Both are
exposed as factories — `build_reranker()`, `build_embeddings()` — so each tool keeps
ownership of its own model choice while the built client is injected into the pipeline,
which is what keeps the unit tests hermetic.

**Why:** the one-rule LangChain scope names the reranker explicitly. This is net-new code,
so writing it on the raw OpenAI SDK would have been deliberately adding to the pending
migration debt rather than meeting the current rule. Embeddings were the open question —
the rule enumerates LLM calls and says nothing about them — and were brought in for the
same reason: one client library for every OpenAI call, no per-call-type exceptions to
remember.

**Rejected:** matching the gate and rewriter on the raw SDK so all of `retrieval/tools/`
shares one idiom, then migrating all three in a single later commit. Cleaner in the
interim, but it means knowingly writing code the design already calls wrong. Also rejected:
migrating the gate and rewriter in this branch, which would widen a retrieval-toolbox
branch into two already-merged tools owned by another session's work.

**Costs, accepted:**

1. **`openai` downgraded 3.0.0 → 2.54.0.** `langchain-openai` pins `openai<3,>=2.45`. The
   gate and rewriter's `client.chat.completions.parse` exists in 2.x and their tests pass
   unchanged, but this branch changes the major version of a shared dependency. After the
   gate and rewriter migrate, `openai` is imported only for `OpenAIError`.
2. **A transitional third client.** `run_retrieval` now takes `client` (raw SDK, for the
   gate and rewriter), `embeddings`, and `reranker`. It drops back to two when the
   migration lands.
3. **Loose typing at the boundary.** `with_structured_output` is annotated as returning
   `dict[Any, Any] | Any`, so a precise `Runnable[..., RerankScores]` is not expressible.
   Rather than cast, the result is narrowed with `isinstance` in `run_reranker` and
   anything off-schema takes the fail-open path the design already specified.

**Not changed:** the reranker's behavior contract is identical — candidates in, the same
candidates out reordered, fused order preserved on any failure. Only the client changed.

---

## Frontend boundary: responses are cast, not validated — Zod rejected

**Timestamp:** 2026-08-12 11:42 -07:00

**Decision (user's call, against the AI's recommendation):** the frontend declares its API
shapes as TypeScript interfaces and casts responses into them. There is no runtime schema
layer.

**The asymmetry this creates, stated plainly:** the backend validates every row it reads
into Pydantic models precisely so "schema drift surfaces as a typed validation error at
the boundary" (`persistence/rows.py`). The frontend now does the opposite. TypeScript
types are erased at compile time, so `await res.json() as Conversation` is an unchecked
assertion — if the backend renames `page_start`, the frontend produces
`#page=undefined` and a broken deep link, with no error anywhere near the boundary the
data crossed.

**Rejected — Zod schemas as the single source of truth (the AI's recommendation):** one
declaration per payload, TS types inferred from it, `safeParse` at every boundary and a
typed error into the existing UI error state. The argument for it was situational rather
than general: the backend contract is still moving, this branch was written against an
`events.py` that is not yet merged, and cutover is the moment a validator earns its keep.
Cost was one runtime dependency and a schema per payload. The user rejected it, and
`CLAUDE.md` backs that: this is a demo optimized for a reader following the code end to
end, coverage is not graded, and a validation layer that never fires before submission is
weight without a reader-visible payoff.

**Consequence, recorded as debt in `DESIGN.md`:** contract drift will present as a broken
render rather than a named error. The mitigation actually in place is cheaper and
narrower — the frontend types were written by reading `chat/events.py` and
`chat/context.py` directly rather than from the design prose, and three drifts were caught
that way (see the AI usage record).

---

## The frontend mock is a test fixture, not a dev-time fake backend

**Timestamp:** 2026-08-12 11:42 -07:00

**Decision (user's call):** the only mock is a stubbed `fetch` inside Vitest. There is no
mock in the dev browser. `npm run dev` renders a UI wired to a backend that must really
exist.

**Why this still de-risks the transport:** the stub returns a real `Response` wrapping a
real `ReadableStream`, so the production `fetch` call, the frame splitter, the buffering
across chunk boundaries, and the sentinel handling all execute unmodified. What is faked
is the socket, not the client. Tests deliberately feed frames split mid-frame
(`event: tok` / `en\ndata: …`) because that is the failure the parser exists to survive.

**Rejected — MSW serving one handler set to both Vitest and the dev browser (the AI's
recommendation):** it would have made the graded streaming and loading/error states
visible in a browser today, from the same definitions the tests use. Rejected as a
dependency bought for demo convenience. Also rejected: a Vite dev-server middleware
serving real chunked SSE, which needs no new runtime dependency but produces two separate
mock implementations of one contract that then drift.

**Cost accepted:** the loading, streaming, incomplete and error states are asserted in
jsdom and have never been looked at. Their first appearance on a screen will be after the
backend endpoints land.

---

## Frontend conversation cache and stream ownership — supersedes "Caching: none, frontend or backend"

**Timestamp:** 2026-08-12 11:42 -07:00

**Decision:** `state/ConversationStore.tsx` holds an in-memory `id → ConversationDetail`
map — no TTL, no eviction, no persistence — and owns the in-flight streams, keyed by
conversation id. This is a deliberate exception to the no-caching rule, which stays in
force everywhere else.

**The reason is correctness, not performance.** The performance case was examined and
rejected on its own terms: a handful of conversations against a local backend, over
history that is global, shared, and mutable by anyone, means a cache is stale by design
and saves nothing worth having. What justified it is that `messages` rows are written
server-side only at stream `done`. An answer streaming into `ChatArea`'s state exists
*nowhere else* — not on the server, not in any other component — so switching
conversations mid-answer unmounts the component and destroys it permanently, with nothing
to refetch. Moving stream ownership up fixes that, and once state lives above the
components the cache is what that state already is.

**Rejected — keeping "caching: none" and refetching on every select:** smallest diff, no
design change, always fresh. Rejected because it leaves the lost-answer defect in place.
Also rejected: adding the cache but leaving the stream in the component, which buys the
performance win that was not needed and skips the correctness win that was.

**Also rejected — `localStorage` persistence:** survives a reload, and is the worst fit
here. History is shared and global, so a persisted view is one user's stale snapshot of
data another user has since changed.

---

## Conversation lifecycle: created lazily on the first question

**Timestamp:** 2026-08-12 11:42 -07:00

**Decision:** "New chat" creates nothing. The conversation is `POST`ed on the first
question, with a title derived from that question, and only then does the query stream
start.

**The API surface decides this, not taste.** The endpoint list has no `DELETE` and no
`PATCH`. So an eagerly-created conversation can never be removed, and a title set at
creation can never be corrected. Creating on click would put permanent, empty, identically
named rows into a list every user shares, and deriving a meaningful title requires the
question, which does not exist yet at click time.

**Cost accepted:** one extra round trip sits between pressing enter and the first token,
because `POST /conversations` must resolve before `POST /conversations/{id}/query` can
start. Measured against permanently littering a shared list, this is the cheaper of the
two.

**Rejected:** eager creation plus a new `DELETE` endpoint and empty-conversation cleanup.
It solves the litter properly rather than avoiding it, but expands a frontend branch into
the backend API surface to buy back a single round trip.

---

## A stream ending without a terminal event keeps its partial answer

**Timestamp:** 2026-08-12 11:42 -07:00

**Decision:** the client tracks whether `done` or `error` arrived. A body that ends
without either is an interruption: the text already received stays on screen, labeled
incomplete. Nothing is discarded and nothing is retried.

**Why the tracking is not optional:** at the byte level a dropped connection and a clean
finish are the same event — the reader ends. Absence of a terminal event is the only
evidence available, so it has to be recorded as the stream is consumed rather than
inferred afterwards.

**Rejected — discarding the partial and showing an error alone:** a cleaner state model,
and in a clinical domain there is a real argument that a truncated answer is the more
dangerous artifact. Rejected because the partial and its resolved citations are genuinely
useful, and an explicit "this answer is incomplete" marker is more honest than making the
evidence disappear. The domain argument is what makes the marker mandatory rather than
decorative.

**Rejected — a Retry button:** safe to build, since a failed stream persists nothing
server-side and leaves no partial row. Not built: `CLAUDE.md` lists retry logic as
do-not-build-unless-asked, and it is not a graded behavior.

**Related decision — no stop button.** The composer is disabled while its conversation
streams, which guarantees one stream per conversation by construction instead of by
re-entrancy logic. `AbortController` is still plumbed through the client for teardown and
so tests do not leak readers; nothing in the UI cancels. Cancellation is not among the
four graded answer behaviors.


## Render deployment: a `prod` deploy branch and a checked-in Blueprint

**Timestamp:** 2026-08-12 15:04 -07:00

Both services deploy from a long-lived **`prod`** branch, fast-forwarded from `main`, and
are declared in a **`render.yaml` Blueprint** at the repo root rather than clicked
together in the dashboard.

Rejected: creating the two services by hand in the Render UI. It is faster to start and
leaves nothing to review, but the configuration then exists only inside a vendor account
— unreproducible, invisible in the diff, and gone if a service is deleted. The Blueprint
costs one file and makes `rootDir`, health check path, build command, and the full env-var
surface reviewable alongside the code they configure.

Rejected: deploying `main` directly. `prod` decouples "merged" from "live", so a merge
does not ship, and what is live is always a commit that has passed CI.

Rejected: a Render static-site rewrite proxying `/api` to the backend, which would have
made the two services same-origin and deleted the CORS configuration and the
`FRONTEND_ORIGIN` variable entirely. Declined because SSE through Render's static-site
rewrite layer is unverified, and streaming is a graded behavior — not the place to take
an untested dependency to save one env var.

**`DATABASE_URL` must be the Supavisor session pooler (5432).** Two plausible values are
both wrong: Supabase's direct connection host is IPv6-only and Render has no IPv6 egress,
so it fails to connect at all; the transaction pooler (6543) connects and then fails once
psycopg3 begins issuing prepared statements for a repeated query. The session pooler is
the only form that works with a per-request psycopg connection and no pool.

**Free instance tier, accepted.** The backend spins down when idle, so the first question
after a quiet period waits out a cold start before the first token. Paying for an
always-on instance buys demo smoothness and nothing that is graded.
