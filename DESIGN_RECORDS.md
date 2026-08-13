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

## Ingestion is its own top-level project, not a backend package

**Timestamp:** 2026-08-12 11:32 -07:00

**Decision:** ingestion moves out of `backend/ingestion/` to a top-level `ingestion/`
beside `backend/` and `frontend/`, with its own `pyproject.toml`, lockfile, Dockerfile,
and test suite. `backend/Dockerfile.ingestion` and the `backend/ingestion/` stub are
deleted.

**Why:** no API path reaches ingestion and the backend never imports it — Build-Spec §9
already said the two "meet only at Supabase", while the directory tree said they were
one program. Three concrete differences back the split: dependency profile (CV model
weights vs. a lean FastAPI image), runtime (run-once local batch vs. hosted service),
and credentials (Storage read + Postgres write vs. Postgres read + signed-URL minting).
A separate lockfile makes the lean-backend guarantee structural: the backend image
*cannot* pull `unstructured` in, rather than merely not being asked to.

**Rejected:**

1. **`backend/ingestion/` with a dependency group.** The arrangement that existed. Keeps
   one toolchain, but the leanness guarantee then rests on every future `uv sync`
   remembering the right flag.
2. **A shared `db/` project owning the schema for both.** Tidiest on paper, but it breaks
   the already-merged `python -m persistence.migrate` entry point and the healthcheck,
   and rewires backend files that a parallel session is editing.
3. **Ingestion owning `documents`/`chunks` migrations, backend owning the rest.** Matches
   write-ownership exactly, and splits one schema across two runners with no ordering
   guarantee between them.

**Consequence:** the schema keeps a single owner — `backend/persistence/migrations/`,
verified by `python -m healthcheck`. Ingestion assumes the tables exist, validates every
row it reads back into a model, and names the migration step as a prerequisite in its
README. CI grows a third job.

---

## Carving boundaries: a body window, validated against all 17 documents

**Timestamp:** 2026-08-12 11:32 -07:00

**Decision:** the exclusion list is implemented as a *window*, not a per-section
blocklist. The body opens after the last element whose text is exactly
`FULL PRESCRIBING INFORMATION` and closes at the first packaging heading. A numbered
heading is a number 1–17, optional trailing dot, optional `.n`, plus a title-shaped
remainder. Unnumbered structural headings (boxed warnings, `MEDICATION GUIDE`) carve
sections with a null number. Carving splits at the finest heading level.

**Why, with the evidence.** Every rule below was checked against all 17 corpus PDFs
before it was written, and three candidate rules died in the process:

1. **The window collapses two exclusions into one rule.** The contents page is headed
   `FULL PRESCRIBING INFORMATION: CONTENTS`, so an exact-match marker for the bare
   string lands past both HIGHLIGHTS and the TOC. Present in 17/17, at pages 2–4.
2. **Packaging is terminal.** Warfarin.pdf was the test: eleven `PRINCIPAL DISPLAY
   PANEL` blocks plus the product-data tables run from page 30 to the last page, with
   no prescribing content after them. True in 17/17.
3. **Case does not signal level — the previously recorded rule was wrong.**
   `8.1  PREGNANCY` is an ALL-CAPS subsection in Warfarin_2. Level now comes from the
   number shape alone. The corpus-quirks list in `DESIGN.md` is corrected.
4. **Numbering variants mix within one document.** Warfarin_2 has `1.  INDICATIONS` and
   `4  CONTRAINDICATIONS` on the same page, so the optional dot is a per-heading rule.

**Rejected on evidence:**

1. **A word-count floor on heading titles** (at least 2 words, written to reject
   `1 mg:`). It also rejected `5.1 Hemorrhage`, `11 DESCRIPTION`, and
   `5.4 Proarrhythmia` — measured at 12–16 top-level sections per document instead of
   the true 15–16, and it silently dropped roughly a quarter of all subsections.
   Replaced by a 3-character floor.
2. **A monotonic section-order guard** (accept a heading only if its number exceeds the
   last accepted one). Sound-sounding, and false: 6 of 17 documents are non-monotonic in
   extraction order, so it would have rejected real headings.
3. **Trusting the numbered pattern alone inside the window.** It matched carton text —
   `1 mg:`, `10 mg White (dye`, `30 Tablets` — 27 times in Warfarin.pdf. The
   section-number bound of 1–17 (PLR defines exactly those) plus an uppercase title
   remainder and a terminator rule removes the class.

**Consequence:** with the shipped rules, all 17 documents resolve 15–16 top-level
sections (1–17 with the usual omissions of 9 and 15) and 25–60 subsections, and zero
false headings appear after the packaging boundary.

**Known limit:** this validation ran through `pypdf` text, not through `hi_res`, which
is what ships. `hi_res` gives better reading order and real element categories, so the
rules should hold or improve — but the first live run is the first time the two meet.
Logged in `DESIGN.md` as debt.

---

## Document identity comes from one LLM call per document, and fails loudly

**Timestamp:** 2026-08-12 11:32 -07:00

**Decision:** `drug_name`, `manufacturer`, and `formulation` are read by a single
`gpt-5-mini` structured-output call per new or changed document, over the label opening
and closing text. A failed call, an unparsed response, or an empty required field
raises and stops the run.

**Why:** the bucket is the source of truth, so ingestion sees only an object key and
PDF bytes — nothing else in the pipeline knows what drug a document is for, and two of
the three fields are `NOT NULL` and appear in citations. The label text carries all
three, but in labeler-specific prose. `gpt-5-mini` is already the gate and rewriter
model, so no new model enters the stack. The call runs 17 times at ingestion, never per
query.

**Rejected:**

1. **A hand-authored manifest in the repo** (the AI recommendation). Deterministic and
   free, but it makes the bucket only half the source of truth: adding a document would
   mean editing code, and the manifest is exactly the kind of parallel list that goes
   stale against what is actually stored.
2. **Regex parsing of the title and "Manufactured by" block.** Free and deterministic
   until a labeler writes it differently, and a bad parse fails silently into a
   citation — the worst failure direction for this field.
3. **Falling back to the filename on failure.** Rejected for the same reason pages fail
   loudly: a `NOT NULL` column holding a guess is worse than a stopped run.

---

## A kept chunk that moved is relocated, not re-embedded

**Timestamp:** 2026-08-12 11:32 -07:00

**Decision:** chunk-level reconciliation has four outcomes, not three: insert, delete,
**relocate**, and unchanged. A chunk whose content hash is unchanged but whose page,
index, or section differs has those columns updated in place, inside the same
per-document transaction, with its embedding untouched.

**Why:** the chunk hash is content-only by design, so it cannot see that a revised label
pushed a paragraph onto a different page — and `page_start` is what the citation
deep-links to. Without this, a revision leaves correct-looking chunks pointing at the
page they used to be on, which is precisely the "citations must be real, not decorative"
failure the rubric names.

**Rejected:**

1. **Leave kept chunks untouched.** Simplest diff, and it accepts stale page citations
   after any revision.
2. **Fold page and index into the content hash.** Always correct, and a one-page shift
   early in a label would re-embed everything after it — paying embedding cost for text
   that did not change.

**Also decided:** content that repeats within a single document collapses to one chunk.
`UNIQUE (document_id, content_sha256)` means the second copy is the same row, so
emitting it twice would abort the transaction.

---

## Pages are resolved from splitter offsets, not inferred from neighbors

**Timestamp:** 2026-08-12 11:32 -07:00

**Decision:** each element contributes a segment to its section joined text, and a
chunk page span is read from the segments its character range covers, using the offset
the recursive splitter reports (`add_start_index`, with whitespace stripping disabled so
the offsets address the text that was passed in). A range covering no segment raises.
Cross-page tables are stitched into a single element that carries `page_start` and
`page_end`, so `PageElement` holds a span rather than one page.

**Why:** page is the guaranteed citation floor and `NOT NULL` in the schema, so it has
to come from something the extractor actually reported. The first version inferred a
stitched table end page from the page of the *next* element, which is a guess that is
wrong whenever a table is the last block on its page.

**Rejected:** locating each chunk by searching for its text in the section
(`str.find`). Works until the splitter strips whitespace or a section repeats a phrase,
and then it silently returns the wrong offset — and therefore the wrong page.

---

## Retrieval package restructured into pipeline stages — supersedes the flat `tools/` folder

**Timestamp:** 2026-08-12 12:06 -07:00

**Decision:** `retrieval/tools/` is replaced by three stage packages named for what they
do in order — `query/` (advice gate, query rewriter, shared transcript rendering),
`search/` (embeddings client, dense leg, sparse leg, shared chunk columns and row reader),
`ranking/` (RRF fusion, LLM reranker). A new `retrieval/contract.py` holds the vocabulary
that crosses the package boundary: `HistoryMessage`, `ScoredChunk`, `Refusal`,
`Retrieved`. `tests/retrieval/` mirrors the source layout.

**What was wrong with the flat folder:**

1. **Two of its nine modules were not tools.** `chunks.py` held three unrelated things
   under one filename — a SQL column fragment, a database row reader, and `ScoredChunk`,
   a domain type flowing through fusion, reranking, the pipeline, and eventually `chat/`.
   `history.py` held a type the API needs beside a prompt helper private to two tools.
2. **The return contract was scattered across three files.** A caller handling
   `run_retrieval`'s result imported `Refusal` from a tool module, `Retrieved` from the
   pipeline, and `ScoredChunk` and `HistoryMessage` from two more tool modules — three of
   the four being internals of tools the caller has no other business knowing about.
3. **The folder hid the pipeline order.** Read alphabetically it was advice_gate, chunks,
   dense_search, embedder, fusion, history, query_rewriter, reranker, sparse_search —
   nothing indicating what runs when.

**Why now:** nothing outside `retrieval/` and `tests/` imported the package yet — checked
across all four active worktrees, including the one building `chat/`. The same move after
generation and the API wire in would touch several sessions' files instead of none.

**Rejected:** keeping `tools/` and merely evicting the two non-tools into `retrieval/`.
Smaller diff and it preserved the recorded `tools/` naming convention, but it left the
folder listing seven modules alphabetically with the stage order still invisible, and it
pushed five modules up to the package root. Also rejected: merging the dense and sparse
legs into one `search.py` — they read the same table but are genuinely different
mechanisms (HNSW vector distance vs `tsquery` ranking), and one file per tool is the
established convention.

**Naming note:** the contract module is `contract.py`, not `models.py`. In a codebase
where `RERANKER_MODEL = "gpt-5-nano"`, "model" already means something else.

**Verified:** `tests/retrieval/` does not shadow the `retrieval` package on `sys.path` —
`pythonpath = ["."]` resolves the real package first, confirmed by a probe test before it
was removed. Ruff, strict mypy, and all 33 tests pass; the restructure changed no
behavior.

---

## Ingestion's OpenAI calls move onto `langchain-openai` — supersedes its raw-SDK adapters (11:32)

**Timestamp:** 2026-08-12 12:01 -07:00

**Decision:** ingestion's two OpenAI calls are built on `langchain-openai`, matching the
one-rule LangChain scope that landed on `main` while the ingestion branch was in flight.
Identity extraction is `ChatOpenAI(model="gpt-5-mini").with_structured_output(
DocumentIdentity)`; chunk embedding is `OpenAIEmbeddings(model=EMBEDDING_MODEL,
dimensions=EMBEDDING_DIMENSIONS)`. Both are exposed as factories —
`build_identity_model()`, `build_embeddings()` — and the built clients are injected into
`ingest_document`, which is what keeps the new tests hermetic.

**Why:** the rule names embeddings for "both ingestion and query embedding" explicitly,
so this was not an open question the way it was for the reranker branch. Ingestion was
written on the raw SDK a few hours before the rule landed; leaving it there would have
added a third project to a migration debt that already covers the gate and rewriter,
for code that had not shipped yet.

**Consequences:**

1. **Manual batching deleted.** `OpenAIEmbeddings` batches internally, so the hand-rolled
   64-item loop and its ordering guard (`sorted(response.data, key=index)`) went with it.
   The length check stayed: vectors are zipped with chunks at insert time, so a short
   response would attach the wrong embedding to a chunk rather than fail.
2. **`openai` pinned to 2.x here too.** `langchain-openai` pins `openai<3`, and ingestion
   resolves to the same 2.54.0 the backend carries. It is now imported for `OpenAIError`
   and nothing else.
3. **Two model clients instead of one.** `ingest_document` takes both a `BaseChatModel`
   and an `Embeddings`; the raw SDK client that served both is gone.
4. **`isinstance` at the boundary, not a cast.** `with_structured_output` is annotated
   `dict | BaseModel`, so `extract_identity` narrows the result and treats anything
   off-schema exactly as a failed call: the document is not registered.

**Not changed:** the failure direction. Identity extraction still fails loudly — the
opposite of the reranker's fail-open — because `drug_name` and `manufacturer` are
`NOT NULL` and appear in citations.

**Also confirmed against `main` in the same pass:** the splitter stays
`langchain-text-splitters`' `RecursiveCharacterTextSplitter` (the one LangChain
component the rule admits beyond the model clients), and extraction keeps calling
`partition_pdf` directly rather than `UnstructuredPDFLoader`, which flattens away the
per-element `page_number` and table HTML that the page floor and table handling depend
on. The merged chat layer reads `drug_name` straight into `Citation.drug`, and its test
fixture expects the lowercase generic (`"warfarin"`) that the identity prompt specifies.

## API layer: the six endpoints, wiring, and the sync/async boundary

**Timestamp:** 2026-08-12 12:52 -07:00

Built the backend API layer (worktree `be-blockers`). Decisions and rejections:

- **OPENAI_API_KEY env trap fixed by explicit credentials, not env mutation.**
  `build_embeddings()` / `build_reranker()` read the key from process env, but
  `load_settings()` never exports `.env` into `os.environ` — local dev with only a
  `.env` file failed at first query. Both factories now take `api_key: str`, matching
  `generation_model(api_key)`. Rejected: `os.environ.setdefault(...)` at startup —
  ambient state mutation, the exact thing the explicit-input stance exists to avoid.
- **Composition root + per-request DB connection.** `api/state.py` builds every shared
  client once in the FastAPI lifespan (settings, ChatOpenAI generation, embeddings,
  reranker, raw OpenAI for gate/rewriter, Supabase storage); one typed accessor
  contains the single `cast` off `app.state`. Connections open per request via a
  dependency. Rejected: a shared long-lived connection (unsafe once concurrent
  requests run on threads) and `psycopg_pool` (new dependency and tuning surface a
  demo does not need; Supabase's pooler absorbs churn).
- **Sync/async boundary.** Non-streaming endpoints are plain `def` — FastAPI's own
  threadpool handles them. Only the SSE query endpoint is async; its blocking work
  (`run_retrieval`, persistence writes, the document join) is offloaded with
  `run_in_threadpool` inside `api/query.py`. Rejected: converting the retrieval
  pipeline to async — a rewrite of every retrieval module for zero demo benefit.
- **SSE hand-rolled, `sse-starlette` rejected.** `encode_sse` already existed and is
  unit-tested; `StreamingResponse(media_type="text/event-stream")` plus a 4-line frame
  generator finishes the job. `sse-starlette` would add a dependency in order to make
  the tested encoder dead code.
- **Chunk→document join is one `WHERE id = ANY(...)` query plus a pure pairing**
  (`persistence/documents.py` + `api/join.py`). A missing parent raises KeyError —
  FK-guaranteed, so absence is corruption. Rejected: joining documents into the
  search-leg SQL (widens the retrieval contract another session owns).
- **An errored stream persists no assistant message.** The partial answer reaches the
  client via the `error` event only; shared history never shows a truncated answer as
  if complete. The assistant write happens at `done`, before the event is yielded, so
  a failed write surfaces instead of following a success signal. A gate refusal *is*
  persisted (empty sources snapshot) — a reader who never saw the stream still sees
  the refusal.
- **Bucket name fixed as `CORPUS_BUCKET = "corpus"`** in `config.py`, beside the
  embedding constants, same fixed-not-env-tunable reasoning. The upload script (not
  yet written) must seed this bucket name. Signed-URL TTL is 300 s. The installed
  storage3 SDK returns the signed URL absolute under both `signedURL`/`signedUrl`
  keys and returns None on failure — the adapter validates the payload so a failed
  signing raises at the boundary instead of returning a null URL.
- **Trace response** wraps the collected `AnswerTrace` plus per-chunk scores read off
  `ScoredChunk` (`api/models.py:TraceResponse`); a refusal traces as its canned text
  with an empty retrieval list. Trace mode writes nothing to history, including the
  user message; covered by unit tests on the write sequencing instead
  (`tests/test_query.py`).

---

## Eval harness runs in-process — supersedes driving the endpoint's trace mode over HTTP

**Timestamp:** 2026-08-12 13:00 -07:00

**Decision:** the eval harness is a backend package, `backend/eval/`, run as
`python -m eval`. It imports the retrieval/chat core directly — `run_retrieval()`, the
chunk→document join, `trace_answer()` — with its own psycopg connection (hosted
Supabase) and its own model clients. No HTTP, no running server, no `?trace=true`. The
driver deliberately calls the core rather than the endpoint's composed operation: the
operation writes conversation history, and a ~72-call eval run must not bury the shared
UI in robot conversations. The history write stays covered by unit tests.

**Why:** the user's requirement — the harness must not depend on a live backend to run.
In-process also takes the query endpoint off the harness's critical path (the endpoint
was unbuilt when this was decided), drops the HTTP-client/serialization layer entirely,
and keeps the run typed end to end: `RetrievalConfig` in, real `ScoredChunk`s out,
nothing parsed back out of JSON into restated shapes. The "measure the path users get"
goal is served *more* directly than over HTTP — the harness calls the very functions
the endpoint composes.

**Rejected:**

1. **Driving `?trace=true` over HTTP** (Build-Spec §10 and the prior DESIGN.md shape) —
   needs a server up and an endpoint built; restates every trace type client-side.
2. **A stub backend serving canned traces** — throwaway code, and a contract the real
   endpoint could silently drift from.
3. **Calling the query operation** — writes robot conversations (above).
4. **Location alternatives:** `scripts/verification/` (import gymnastics or a path
   dependency into the backend; its README now points at `backend/eval/`) and a
   top-level `eval/` project (a second lockfile for zero new dependencies — the judge
   uses `ChatOpenAI`, which the backend already carries). `backend/eval/` follows the
   `healthcheck.py` precedent: backend-resident, locally run, live-service-touching,
   excluded from the deployed image via `.dockerignore`; `eval/runs/` is gitignored.

**Consequence, deliberately left unreconciled:** the harness was `?trace=true`'s only
stated consumer, and this session decided to drop trace mode from the endpoint —
but the API session (worktree `be-blockers`) concurrently built and recorded it.
Keep-or-drop is now an endpoint decision to settle at the API merge; the harness is
indifferent either way.

---

## Eval suite and scoring: dual-lens metrics, single-turn cases, four configurations, gpt-5 judge

**Timestamp:** 2026-08-12 13:00 -07:00

**Decisions (all user-settled this session):**

1. **Dual-lens retrieval scoring.** Every rank metric (Recall@K, MRR, Precision@K)
   reports **strict** (exact `document_id`) and **lenient** (any same-drug sibling
   label) at both document and section granularity. Six of ten drugs have sibling
   labels: lenient-only would hide same-drug discrimination failures, strict-only would
   report retrieval failures that are not failures — the sibling label says the same
   thing. The gap between the lenses is itself a reported finding. Rejected: either
   single lens alone.
2. **Single-turn suite only.** 18 cases: 7 single-section/table lookups, 3
   cross-document synthesis, 3 discrimination traps carrying `forbidden_drugs`, 3
   unanswerable, 2 personal-advice. Rejected: multi-turn follow-up cases (history
   plumbing through driver and ground truth). Accepted cost, recorded as a known
   limitation: the rewrite toggle's contextualization job — the delta it exists to
   measure — goes unmeasured; on single-turn input it exercises only normalization.
3. **Four configurations** — dense, dense+sparse, dense+rerank, dense+sparse+rerank —
   with gate and rewriter always on: the advice cases need the gate, and a rewrite-off
   configuration on a single-turn suite would measure only normalization for the price
   of a fifth full pass.
4. **The judge is `gpt-5`** via `ChatOpenAI.with_structured_output` — closes the open
   question in the 03:25 eval-judge entry. Not the generator's model, so self-preference
   bias is avoided; the same-provider caveat stands as a known limitation.
5. **Record/replay.** Every run saves its traces to `eval/runs/<timestamp>.json`;
   `--score-only <run>` re-scores a saved run with zero pipeline or judge re-spend. The
   saved run is the artifact behind DESIGN.md's failure analysis.

**Built in this pass (hermetic, in CI):** `eval/cases.py`, `eval/trace.py`,
`eval/configs.py`, `eval/scoring/{retrieval,grounding,behavior}.py`, and their tests
(15, in `tests/eval/`, fixtures in the shared root conftest — a second conftest
collides under mypy's namespace-package module mapping). Still to build: `suite.py`
(authored ground truth), `judge.py`, `report.py`, `driver.py`, `__main__.py`.

---

## Eval harness completed: driver on the composition root, fail-open judge, guarded entry point

**Timestamp:** 2026-08-12 13:40 -07:00

**Decisions made finishing the harness (judge, report, driver, entry point):**

1. **The driver reuses `api/state.py`'s `build_clients()`** rather than constructing
   its own model clients. The composition root exists exactly so every caller builds
   the same clients from explicit settings; a second assembly in the harness would be
   the drift point the root was built to remove. The driver composes
   `run_retrieval` → `fetch_documents` + `attach_documents` → `trace_answer` — the
   same functions `api/query.py` composes — minus the history writes.
2. **The judge fails open.** A failed or off-schema `gpt-5` call returns `None`; the
   report counts and lists the case as *unjudged* instead of the run dying sixty calls
   in. Opposite direction from the advice gate (fail closed) because the judge is
   measurement, not a safety behavior — a missing measurement must be visible, not
   fatal. Its prompt lives in `prompts/eval_judge.py` per the one-per-file convention.
3. **Report metrics are computed at K = 8** — `RetrievalConfig.final_limit`, the
   chunks generation actually sees. Grading retrieval on what the app answers from,
   not on a wider candidate pool, keeps the number honest to the user experience.
   Rejected: reporting a second K (more numbers, no decision they would change).
4. **`python -m eval` refuses to run while `suite.py` contains "TODO".** The suite
   ships as a typed skeleton for human authoring; the guard makes a half-authored
   suite cost zero API spend instead of producing a garbage run. `--score-only`
   re-scores a saved run: zero pipeline calls, judge re-runs (deterministic scoring
   is free; verdicts are not persisted in the run file).
5. **Traces and report land beside each other** — `eval/runs/<stamp>.json` and
   `<stamp>.report.md`, gitignored; progress goes to stderr so the report stays
   pipeable.

---

## Eval suite authored: 18 cases, every expected source verified against extracted label text

**Timestamp:** 2026-08-12 13:58 -07:00

**What was done:** all 18 cases in `eval/suite.py` were drafted and their ground truth
verified against pypdf text extractions of the 17 corpus PDFs (same heading rules as
`ingestion/carving.py`, so recorded section numbers match what ingestion will store).
Composition: 6 lookups + 1 table-backed lookup (digoxin § 7.2 interaction table),
3 multi-document synthesis, 3 discrimination traps with `forbidden_drugs`,
3 unanswerable, 2 personal-advice. Four questions carry brand names (Eliquis,
Coumadin, Wellbutrin, Zoloft) to exercise the rewriter's normalization.

**Findings from verification, kept because they shape scoring:**

1. **Sibling labels misalign their numbering in two places.** Warfarin_2 files Missed
   Dose under 2.5 (2.6 in Warfarin/Warfarin_3) and Drugs that Increase Bleeding Risk
   under 7.2 (7.3 elsewhere) — its 7.2 collides with the *other* labels' 7.2 CYP450
   Interactions. Cases were therefore authored against sections whose numbers align
   across siblings; the warfarin § 7.x collision is recorded as lenient-lens noise on
   the warfarin×amiodarone case.
2. **Amiodarone.pdf is the intravenous label.** Its pulmonary content (§ 5.5) covers
   acute-onset injury and early fibrosis; the lookup and its expected answer were
   written from that text, not from the oral label's chronic-toxicity profile.
3. **All three unanswerables are proven absent:** "metformin", "albuterol", and "Reye"
   have zero matches across all 17 extracted texts. The aspirin case is deliberately
   adversarial — aspirin itself appears throughout the corpus in bleeding-risk
   interaction text, but Reye's syndrome content does not exist in it.
4. **Apixaban § 2.1's dose-reduction criteria are prose in these labels,** not a
   table, so the table-backed lookup is the digoxin § 7.2 interaction table instead;
   the warfarin×amiodarone synthesis case also reads from warfarin's § 7.2
   inhibitor/inducer table.

**Provenance:** drafted by the AI assistant and verified quote-by-quote during
drafting; recorded as AI usage in `AI_USAGE_RECORDS.md`, pending owner review since
the assignment requires the test set be authored by the submitter.

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


## Conversation detail response flattened; OpenAI failures become a typed 502

**Timestamp:** 2026-08-12 13:39 -07:00

Two API-layer fixes found by checking the merged backend (PR #14) against the
frontend contract pinned in `frontend/src/api/types.ts` (branch `api-contract-fixes`):

- **`GET /conversations/{id}` returned a nested `{conversation, messages}` object**
  while the frontend declares `ConversationDetail extends Conversation` (flat) and
  caches details keyed on `detail.id` - on the nested payload that read is
  undefined, so every loaded conversation cached under the key `"undefined"` and
  the detail view never rendered. Fixed by making the backend model inherit
  `ConversationRow` (flat) - the backend moved because `types.ts` is the pinned
  contract both sides were built against. Rejected: changing the frontend to the
  nested shape, which would ripple through the store and its tests for no gain.
- **An `OpenAIError` during retrieval surfaced as a raw 500.** The stream has not
  started at that point, so it can be a real HTTP error: a second exception handler
  beside the existing `psycopg.Error` -> 503 maps `OpenAIError` -> 502
  `language model unavailable`. Mid-stream failures keep their existing path (an
  `error` event on the already-open stream, handled in the chat layer).

Route-level tests cover both: the flat shape (including `detail.id`) and the 502.


## Answer-path composition pulled into a `conversation/` package

**Timestamp:** 2026-08-12 14:30 -07:00

The chat/persistence/API side had no equivalent of `run_retrieval()` — no single
function that resolves one question — so every caller re-implemented the composition.
Audit found the same two shapes copied across the codebase:

- **The `Refusal | Retrieved` branch, written four times:** `api/query.py`
  (stream + persist), `api/routes.py::build_trace` (JSON trace), `eval/driver.py`
  (harness), plus a fifth canned-vs-generated branch inside `chat/answer.py`.
- **The "fold an event stream into answer + sources" loop, written twice**, as
  identical `match`/`case` blocks: `chat/answer.py::trace_answer` (for the trace) and
  `api/query.py::answer_events` (for the history write). Two copies of the code that
  decides what gets stored versus what gets scored is exactly the pair that must not
  drift.
- **The chunk→document join re-composed three times**, and `api/` owning domain logic
  generally (`api/join.py`, `api/query.py`, `build_trace` defined below its caller).

**What was built.** A new `conversation/` package — the composition layer that was
missing — holding `prepare_turn()`, which runs retrieval, the join, and the answer
stream, and returns a `Turn`. `chat/` gains a `contract.py` (the vocabulary callers
speak, mirroring `retrieval/contract.py`) and loses `answer.py`/`events.py`; SSE
framing moves to `api/sse.py`, so the domain no longer knows its transport.

**The move that collapsed the duplication: `Turn` deliberately does not carry
`Refusal | Retrieved`.** A refusal is a turn whose query is None, whose chunks are
empty, and whose events are the canned stream. Because the canned stream already folds
to `answer=text, sources={}` — the same shape a generated answer folds to — every
downstream branch disappears: the trace endpoint, the history write, and the eval
driver each read `Turn` fields and none of them tests the outcome. Four branches became
one, in `prepare_turn`. `eval/driver.py::refusal_trace` was deleted outright; the
harness now provably measures the same path users get, because there is only one path
to call.

Persistence became a pass-through wrapper (`persist_on_done`) rather than a pipeline
step, which is what lets the SSE endpoint persist while the trace endpoint and the
harness do not, with neither being a special case of the other.

**Rejected: putting `prepare_turn()` in `chat/pipeline.py`** to avoid adding a package.
It would have made `chat/` import `retrieval.contract`, turning a self-contained
generation tool into a composer and inverting the layering the retrieval package
established. Same de-duplication either way; the naming and dependency direction were
the whole question.

**Also moved: `api/state.py` → `clients.py` at the backend root.** Composing retrieval
with chat needs the client bag, and importing it from `api/` would have made
`conversation/` depend on the web layer. It also fixes a pre-existing inversion —
`eval/` was reaching into `api.state` for `build_clients()` despite never serving HTTP.
`app_clients(request)` stayed behind in `api/dependencies.py`, where a `Request` belongs.

**Verification.** The wire contract is untouched: same events, same order, same JSON
(checked by rebuilding the OpenAPI paths and the trace payload). Backend 74 tests pass,
mypy strict and ruff clean, frontend 30 tests pass. Tests were reorganized to follow the
modules (`tests/chat/`, `tests/api/`, `tests/conversation/`), and four copy-pasted
`make_document` helpers plus two fake-model classes collapsed into `conftest.py`
fixtures.


## First live ingestion run: two connection failures, one real durability bug

**Timestamp:** 2026-08-12 15:12 -07:00

The first-ever live run of the ingestion job (Docker, against hosted Supabase) surfaced
three findings, none of them in the carving rules the debt list flagged as the risk:

1. **Docker cannot reach Supabase's direct DB host.** `db.<ref>.supabase.co:5432` is
   IPv6-only (no A record), and Docker Desktop containers here have no IPv6 route. Fix:
   `ingestion/.env`'s `DATABASE_URL` now points at the IPv4 session pooler
   (`aws-0-us-east-2.pooler.supabase.com:5432`, username `postgres.<ref>`). Host-side
   tools (backend `.env`) still use the direct host, which works from the host machine.

2. **The pooler idle-kills the run-long connection.** With one connection held across
   the whole run and `hi_res` extraction leaving it idle for minutes per document, the
   socket died after ~13 documents (`SSL error: ssl/tls alert unexpected message`).
   Fix: TCP keepalives on the psycopg connection.

3. **The per-document commit did not exist — the real bug.** `registry.connect()` used
   psycopg3's default `autocommit=False`, so the entire run sat inside one implicit
   transaction and the `with connection.transaction()` blocks in `apply_document` —
   designed as one commit per document — silently degraded to savepoints. When the
   connection dropped at document 14, all 13 "committed" documents rolled back, and the
   re-run reported `17 to ingest, 0 unchanged` against an empty registry. The hermetic
   reconciliation tests could never catch this: it only exists on a real connection.
   Fix: `autocommit=True`, which is the documented psycopg3 pattern for making each
   `transaction()` block a real BEGIN/COMMIT. The idempotent re-run design proved
   itself the moment the fix landed — byte-identical documents skip extraction and
   embedding entirely, so the retry only pays for what never committed.

Rejected alternative for (2)/(3): retry/backoff around the DB writes — rejected as
gold-plating; per-document durability plus cheap re-runs already make a dropped
connection a resumable event, which is the property the design actually wants.

## Query gate widened from advice-only to advice + unsafe + off-topic

**Timestamp:** 2026-08-12 17:17 -07:00

**What changed.** The binary advice gate became a four-valued query gate. One
structured-output call now returns `personal_advice`, `unsafe`, `off_topic`, or `none`,
and each refusing reason streams its own pre-written message
(`retrieval/query/query_gate.py`, `prompts/query_gate.py`, and two new files in
`messages/`). The module, prompt, function, and test were renamed from `advice_gate` to
`query_gate` because "advice gate" had stopped describing what it does.

**Why.** DESIGN.md previously recorded the narrow gate as deliberate: off-topic questions
would "fall through to the honest not-in-corpus path". In practice they did not fall
through honestly. A question about spiders still embedded, still queried pgvector, and
still served the top chunks; generation correctly said the labeling does not cover
spiders and then appended a citation tag for every excerpt it had been handed, so the
user got a decline followed by eight clickable deep links into venlafaxine and apixaban
labels. The narrow gate was cheap for the model but expensive for the user's trust in the
citations. Nothing in the corpus is about spiders, and finding that out after an embed, a
hybrid search, a rerank, and a generation call is the wrong place to find it out.

**What was rejected.**

- *A relevance threshold instead of a wider gate.* Still the marked drop-in in
  `retrieve_chunks()` and still unimplemented — see the standing note in DESIGN.md. It
  answers a different question: the threshold catches an in-domain question the corpus
  happens not to cover, the gate catches a question that was never about medicine. The
  threshold is also the pre-announced live modification for the follow-up interview, and
  spending it here would have bought a worse fix for this particular symptom.
- *Suppressing the `sources` event when the answer looks like a decline.* Rejected: it
  puts string matching on answer text into the transport, and the mapping is sent before
  any token exists to match against. Citations already render only where a tag appears,
  so the honest fix is for the model not to emit tags it did not answer from.
- *Refusing questions about drugs outside the corpus as off-topic.* Rejected explicitly,
  and the prompt says so: those questions are on topic and must reach the not-in-corpus
  decline path. Three eval cases (`unanswerable-metformin`, `unanswerable-albuterol`,
  `unanswerable-aspirin-reye`) are exactly that shape and would have flipped from a
  correct decline to a wrong refusal.

**The `unsafe` reason is harm-seeking, not harm-adjacent.** The prompt draws the line at
intent: "how much of this would be lethal, and I want to use that" is refused; "what does
the overdose section say" is answered, because reading a label's overdose and toxicity
sections is the entire job of a clinical-operations lookup tool. A gate that flinched at
dangerous-sounding vocabulary would refuse the corpus's most clinically useful content.

## Grounded-answer prompt: answer the question, do not tour the excerpts

**Timestamp:** 2026-08-12 17:17 -07:00

**What changed.** `prompts/grounded_answer.py` gained two instructions: use the excerpts
that bear on the question and ignore the rest, and write no tags at all when declining.
`RetrievalConfig.final_limit` dropped from 8 to 5 (and `eval/report.py`'s `FINAL_K` with
it, so retrieval is still graded at the budget generation actually sees).

**Why.** A question about antidepressant options produced a thirteen-bullet answer in
which all eight served chunks appeared, one bullet each, including trazodone's
take-with-food instruction and mirtazapine's contraindication list. The prompt had told
the model where it *may* draw from and never told it what the reply is *for*, so it
defaulted to summarizing its input — a faithful, grounded, useless answer. The old text
also said "if the excerpts do not contain the answer, say so" without saying what to do
with the tags, and the model kept citing.

**Why 8 → 5.** The first eval run showed the tradeoff already: sparse and rerank each
raise Recall@8 while lowering MRR, so the extra slots at the bottom of the list were
buying marginal recall. Those same low-ranked slots are what the model was padding
answers with. Five keeps the head of a reranked list — where the eval's MRR says the
right section actually sits — and removes the material that made answers sprawl. The next
full eval run measures what recall this costs; that number is not yet in hand, and the
metric tables in the failure analysis above are from the K=8 run.

**What was rejected.** *Capping how many tags an answer may cite.* Rejected as the wrong
lever — it constrains the symptom, not the cause, and a genuine multi-drug comparison
legitimately cites five sources. The cause was a prompt that never named its own purpose.

## Root `make eval` as the eval harness's single command

**Timestamp:** 2026-08-12 17:19 -07:00

The assignment asks the eval harness to run from a single command. It already did —
`python -m eval` — but only if the reader first knew to `cd backend` and that the
project's Python runs under `uv`. Added a root `Makefile` whose only target is `eval`,
running `cd backend && uv run python -m eval`.

The target holds no logic. It does not assemble the suite, pick configurations, or
format anything; `eval/__main__.py` already prints the report to stdout and saves it
beside the traces. Rejected: putting the run's flags (config selection, output paths)
into make variables. That would split the harness's interface across two files and make
the Makefile the place people look for eval behavior, which is exactly backwards — the
harness owns its own CLI, and `--score-only` stays documented as a direct invocation.

Also rejected: adding `test`, `lint`, and `typecheck` targets alongside it. CI calls
those tools directly per workspace (`backend/`, `ingestion/`, `frontend/`), each with
its own toolchain, and a root Makefile that re-declared them would be a second source of
truth for what CI runs. The Makefile exists for the one command the assignment grades.

Known limitation, recorded rather than fixed: `make` is not installed on the primary
development machine (Windows), so the target is unverified by execution there. The
command inside it is verified.

## Eval report gains a cross-configuration comparison, a per-query hit-rate chart, and a progress bar

**Timestamp:** 2026-08-12 17:27 -07:00

The report printed four independent per-configuration sections and left the reader to
diff them by eye. The stretch goal it exists to answer — what do the sparse leg and the
reranker actually buy — was therefore never stated anywhere in the output. Added, after
the per-configuration sections:

- **Metric comparison**, the four configurations as columns, best value per metric in
  bold. Restricted to section granularity under both strictnesses; document granularity
  is the easier question and the configurations barely separate on it, so including it
  would have doubled the table to make the same point twice.
- **Outcome comparison**, behavior checks and judge counts as columns. `behavior_table`
  and `judge_table` were split into `behavior_counts` / `judge_counts` (data) and a
  shared renderer, so the per-configuration and comparison views cannot drift apart.
- **Per-query chunk hit-rate chart** in each configuration's section, and a
  **hit-rate histogram** binning queries into five bands in the comparison. The
  histogram earns its place over the mean alone: a configuration that fails a few
  queries badly and a configuration that is mediocre everywhere can report the same
  Precision@K, and only the distribution separates them.

Hit rate is defined as Precision@K under strict/section — deliberately not a new metric.
A per-query chart of an already-tabled quantity is a second view of one number; a second
*definition* would have been a second thing to defend.

Charts are ASCII (`#` and `.`) inside fenced blocks, not Unicode block characters. The
report prints to a Windows console and is also piped; Unicode bars raise
`UnicodeEncodeError` on a redirected stdout under a cp1252 locale, and the prettier bar
is not worth an output path that crashes.

Progress is now a rewritable single-line bar rather than one line per case (72 lines of
scrollback). It stays on **stderr**, preserving the existing split: stdout is the report
alone, so `make eval > report.md` keeps working.


## Relevance threshold built: `rerank_score >= 3`, chosen from the score distribution

**Timestamp:** 2026-08-12 17:40 -07:00

**What changed.** `RetrievalConfig.min_rerank_score = 3`. `retrieve_chunks()` filters
`ranked` through `relevant_enough()` before the final cut; filtering to zero produces the
existing decline path. `candidate_limit` also dropped from 40 to 10 per leg. This
supersedes the standing note that the threshold was deliberately unimplemented — that
note is removed from DESIGN.md.

**Why 3, and how it was chosen.** Not guessed. The saved traces from the 2026-08-12 K=8
run carry `rerank_score` on all 128 served chunks of the full-hybrid configuration, so
the threshold was swept against real data before a line was written. The distribution is
strongly bimodal — 54 chunks at 0, 43 at 9–10, and a thin middle — with mean 4.19 and
median 3.0.

| cutoff | chunks/query | cases declining | Recall@5 strict/section |
|---|---|---|---|
| 0 (none) | 5.00 | 0 | 0.96 |
| 1 | 3.56 | 3 | 0.96 |
| 3 | 3.31 | 3 | 0.96 |
| 4 | 3.06 | 4 | 0.88 |
| 10 | 1.44 | 6 | 0.58 |

There is a plateau from 1 to 3 where the only cases that decline are the three
`unanswerable-*` cases — which is the behavior the suite wants — and recall is untouched.
At 4 the cliff starts: `synthesis-suicidality-age` loses its last surviving chunk and
strict Recall@5 drops 8 points. **3 is the tightest cut that costs nothing**, and it is
also the median of the observed scores, so "the middle of the outputs" and "the last free
tightening" turned out to be the same number.

**An unscored chunk passes the filter.** `rerank_score` is None in two situations: the
reranker is toggled off, and the reranker's call failed and fell open to the fused order.
Treating None as failing the threshold would have made an OpenAI blip indistinguishable
from an empty corpus — every query declining, with a message claiming the labels do not
cover the question. Rejected. The reranker's existing fail-open contract only holds if
everything downstream of it also treats "no judgement" as different from "judged badly".
The cost is honest and stated: with `rerank=false` there is no threshold at all, so the
dense and dense+sparse eval configurations are unfiltered and the threshold becomes part
of what the rerank toggle measures rather than a hidden third variable.

**What was rejected.**

- *A threshold on `rrf_score` for the rerank-off configurations.* It is a different
  scale with no shared meaning — after the drop to 8 candidates per leg it spans roughly
  0.015 to 0.033 — so a single number could not serve both, and two independently tuned
  numbers would need two independent justifications for one feature.
- *Threshold 4, the mean.* The arithmetic mean is dragged upward by the 9–10 mode; the
  median is the better centre for a bimodal distribution, and the sweep confirms 4 is
  already past the cliff.

**`candidate_limit` 40 → 10, and what it does to fusion.** Each leg now returns 10. This
has a consequence on RRF worth stating because it was not requested and is easy to miss:
the fused score is `1/(k + rank)`, so with `rrf_k=60` a rank-1 hit scores 0.0164 and a
rank-10 hit 0.0143 — a 15% spread across the whole list, against 64% when the legs
returned 40. A chunk found by *both* legs at rank 10 (0.0286) now beats a chunk found by
*one* leg at rank 1 (0.0164). Fusion has become close to a pure vote-counter, with
position as a near-irrelevant tiebreak; the crossover holds for any `rrf_k > 8` at this
depth. Left at 60 because it was not part of the request, and because the reranker
re-sorts the survivors anyway — but if position should carry weight at this candidate
count, `rrf_k` belongs in the 5–15 range. `fused_limit=20` is now inert: two legs of 10
can union to at most 20, so it never cuts.

**Not yet measured.** Every number above is replayed from the K=8 traces, which is sound
for the threshold sweep (the filter is a pure function of stored scores) but not for
`candidate_limit=10`, which changes what is retrieved and reranked in the first place.
The next full eval run is what confirms the combination.

### Eval harness: one rewritten query per case, reused across configurations

**Timestamp:** 2026-08-12 17:53 -07:00

The four configurations each re-ran the query rewriter, an LLM call, so the same case
was searched with different text in each configuration. In the 2026-08-12 run
(`backend/eval/runs/20260812T1554440700.json`), 15 of 18 cases had differing
`searched_query` values across the four. Example — `lookup-trazodone-priapism`: dense
searched "What does the trazodone labeling say about priapism", dense+rerank searched
"What does the trazodone FDA prescribing information say about priapism".

Consequence: every measured delta between configurations mixed the effect under test
with rewriter variance, so the before/after comparison the assignment grades was not
isolating the toggle. The symptom that made it undeniable: the dense and dense+sparse
served sets overlap only ~56%, while zero sparse-ranked chunks were served in either —
a difference the sparse leg cannot have produced.

**Chosen:** compute the rewrite once per case, in `eval/driver.shared_rewrite()`, and
pass it down through `prepare_turn` into `prepare_query` as an optional
`rewritten_query`. When present and `rewrite` is on, it is searched and the rewriter is
not called; when `rewrite` is off it is ignored and the raw query is searched, so the
toggle keeps its meaning. Production is untouched: no request path supplies the
argument, so in-app traffic still rewrites per query. Side effect: the run makes 1
rewriter call per case instead of 4 (and one wasted call on the two advice cases, whose
gate refuses before the rewrite is read — accepted, it is cheaper than the four it
replaces).

**Rejected — run the eval with `rewrite=False` in every configuration.** It removes the
variance but changes what is measured: the suite would then evaluate retrieval over raw
questions, including the brand-name cases (Eliquis, Coumadin, Wellbutrin, Zoloft) that
exist specifically to exercise brand→generic normalization. Those cases would fail for
a reason unrelated to the toggles.

**Rejected — precompute the rewrite and feed it in as the case's `question` with
`rewrite=False`.** Same searched text with less plumbing, but the advice gate would then
see the rewritten text instead of the user's own words, changing what the gate cases
measure, and each trace's `config_name` would no longer describe the config that ran.

**Rejected — seed or cache the rewriter for determinism.** A cache keyed on the question
is the same idea with more machinery, and the project has a standing no-caching
decision; temperature pinning does not make an LLM call deterministic anyway.

**Consequence for the recorded failure analysis:** the 2026-08-12 findings about
cross-configuration deltas (hybrid's cost on look-alikes; the Recall-vs-MRR tradeoff)
are confounded and now carry that caveat in `DESIGN.md`. They need a re-run to be
stated as retrieval effects. Within-case findings (multi-hop collapse, table numerics,
partial section serving) are unaffected.


## RRF damping resized to the candidate list: `rrf_k` 60 -> 10

**Timestamp:** 2026-08-12 18:14 -07:00

**What changed.** `RetrievalConfig.rrf_k` from 60 to 10.

**Why.** 60 is the published RRF default (Cormack et al., 2009), and it was tuned against
TREC runs roughly 1000 results deep. Over a list that long, `1/(60 + rank)` spreads scores
about 17-fold and rank carries real weight. Over the 10 candidates each leg now returns it
spreads them by 11%, and the consequence is not subtle: with `k = 60`, a chunk found by
*both* legs at rank 10 scores 0.0286 and beats a chunk found by *one* leg at rank 1 at
0.0164. Every positional signal was being drowned by a single binary — did both legs find
it — so fusion had quietly become a vote-counter with an ordering tiebreak. At `k = 10`,
rank 1 scores 0.091 against rank 10's 0.050, position separates candidates again, and
cross-leg agreement still compounds without erasing rank. The constant was never wrong; it
was calibrated for a list 100x longer than ours, and shrinking the legs without resizing it
was the actual mistake.

**What was rejected.** *Leaving `k` at 60 and letting the reranker sort it out.* The
reranker does re-sort the survivors, so the fused order matters less than it looks — but
`fused_limit` cuts the list *before* the reranker sees it, so a fusion that cannot rank is
choosing what the reranker is allowed to consider. Fixing the constant is one character;
relying on a downstream stage to paper over it is not defensible out loud.

**Still unmeasured.** No eval run has been made at `k = 10`. The numbers above are
arithmetic, not results.


## The sparse leg had never returned a row

**Timestamp:** 2026-08-12 18:31 -07:00

**What was wrong.** `websearch_to_tsquery` joins bare terms with `&`. A natural-language
question therefore compiled to a conjunction of every one of its lexemes —
`'trazodon' & 'label' & 'say' & 'priapism'` — and demanded a single chunk containing all
of them. Measured against the live corpus over all 18 eval questions: **18 of 18 returned
zero rows**, while `priapism` alone matches 12 chunks. The query rewriter made it worse,
since a longer, more explicit question is a longer conjunction.

**What that means for everything already recorded.** The `dense+sparse` and
`dense+sparse+rerank` configurations were not hybrid; they were dense-only with an empty
second leg, which is why fusion was a passthrough and why 126 of 128 served chunks in the
full-hybrid run carried a null `sparse_rank`. Any claim that the sparse leg *contributed*
something to a served set is false for every run made before this fix — including the
reading that the sparse leg pulls sibling-drug chunks and costs discrimination accuracy.
It cannot have; it returned nothing. Those served-set differences came from the query
rewriter running per configuration, fixed separately in `2953cba`. The stretch goal was
being graded on a leg that never ran.

**The fix.** Rewrite the compiled tsquery's `&` operators to `|`. This asks the question a
keyword leg exists to ask — which chunks share the most terms — and leaves `ts_rank` to
order them. The rewrite is textual, on the compiled tsquery rather than the user's string,
so phrase (`<->`) operators and an explicit `or` pass through intact; keeping those is the
reason `websearch_to_tsquery` was chosen over `to_tsquery` originally. Verified on the live
corpus: `"serotonin syndrome" risk` keeps its phrase as `'serotonin' <-> 'syndrom' | 'risk'`.

**Negation survives syntactically and not semantically, which is a real limitation.**
`bleeding -warfarin` compiles to `'bleed' & !'warfarin'` and becomes `'bleed' | !'warfarin'`,
where the disjunct "any chunk lacking warfarin" matches 1547 of 1711 chunks — a leading `-`
stops excluding anything. Accepted rather than fixed: the string reaching this leg is the
rewriter's output, generated prose containing no `-term` and no quotes, so the operator is
unreachable in practice. Honouring exclusion under disjunction means parsing the tsquery
into `(a | b) & !c`, and a parser with no caller is not worth its own bugs.

**Verified against the live corpus, not a fixture.** After the change all 16 non-refused
eval questions return 10 rows; the top-ranked chunk belongs to the **correct drug** in all
13 answerable cases; and each case now overlaps the dense leg by 1–4 chunks, which is the
first time RRF's agreement term has had anything to compound. The three unanswerable cases
return chunks from unrelated drugs, as they should.

**What was rejected.**

- *Rebuilding the tsquery from `to_tsvector` lexemes joined with `|`.* Cleaner-looking, but
  it discards phrase and negation handling — the whole reason `websearch_to_tsquery` is
  here — to avoid a `replace()` whose only failure mode is a literal `&` inside a quoted
  lexeme, which would degrade one lexeme rather than break the query.
- *Leaving the leg conjunctive and calling it precision.* A leg that returns nothing on
  every question in the suite is not precise, it is off.

**No unit test covers this.** The backend test suite is hermetic and nothing in it touches
Postgres, so a test asserting the SQL string would restate the code rather than check it.
The evidence above is a live measurement against the corpus and is recorded here in place
of a test. A DB-backed retrieval test is the honest follow-up and is not built.

**Still unmeasured.** No eval run has been made with a sparse leg that works. Every
retrieval metric in this repository describes dense-only retrieval, whatever its
configuration was labelled.


## Sentinels are written strictly and read leniently

**Timestamp:** 2026-08-12 18:47 -07:00

**What changed.** `TAG_PATTERN` in `chat/context.py` and `COMPLETE_TAG` in
`lib/sentinels.ts` both go from `[[S1]]` to `[[?S1]]?` — one bracket or two. The prompt
and `sentinel()` are unchanged: `[[S1]]` is still what is asked for and still what is
written into the context block.

**Why.** The model drifts to single brackets on longer answers. Measured over the
2026-08-12 run: **18 of 64 non-refused answers used `[S1]`**, and every one of them
recorded an empty `tags` list. The user-visible cost is a citation rendered as dead
literal text — `[S3] [S4]` sitting in the prose where two clickable sources belong.

**The eval cost is worse, because it is invisible.** `unresolved_tags(trace.tags,
trace.sources)` flags tags that resolve to nothing. An answer whose tags did not parse has
*no* tags, so there is nothing to flag and the grounding check passes. The "grounding
clean 18/18" result, and the claim that all 72 answers cited only actually-served chunks,
were partly measuring answers that cited nothing the harness could see. Reading leniently
takes the harness from 127 parsed citations to 193 over the same run — 66 citations across
18 answers that previously scored as tagless.

**Why not fix it in the prompt alone.** That was the earlier attempt: `530202d` added "in
double brackets exactly as shown". The example that prompted this entry was produced after
that change. A prompt cannot be a parser's contract when the same prompt is also asking
for prose, and the failure is silent on both sides of the wire.

**What was rejected.**

- *Keeping the readers strict so drift stays visible.* That was the original call, on the
  grounds that widening the regex hides how often the model misbehaves. It is wrong here:
  the drift was not visible, it was invisible twice over — dead text in the UI and a
  passing grounding check. Visibility belongs in a metric that counts drift, not in
  breaking the feature.
- *Repairing the answer text mid-stream.* Rewriting `[S1]` to `[[S1]]` in the transport
  would make the backend edit a stream it deliberately passes through untouched. The
  reader is the right place; the wire stays raw.

**A complete `[S1]` is not withheld while streaming.** `TRAILING_PARTIAL_TAG` holds back
unclosed fragments so a half-arrived sentinel never flashes as text. It now holds `[S`,
`[S1`, `[[S1]` and friends, but deliberately not `[S1]`, which is already renderable —
holding it would stall the last citation of every answer until the stream closed.

**Not fixed: the metric that would have caught this.** Nothing counts how often the model
drifts. The lenient reader makes the drift harmless but also makes it unobservable, which
is the same trap in a new place. A drift counter on the eval trace is the honest follow-up
and is not built.
