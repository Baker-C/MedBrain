# DESIGN.md — MedBrain

**Last updated:** 2026-08-12 21:20 -07:00 · Live: <https://medbrain-site.onrender.com/>

## Overview

| Layer | Choice |
|---|---|
| Frontend | React, TypeScript, Tailwind — talks to the backend only through API endpoints. Vitest + Testing Library (jsdom) for its tests |
| Backend | Python, FastAPI, LangChain (`langchain-openai`) — owns all retrieval, reranking, and generation |
| Store | Supabase Postgres + `pgvector` — one store for chunks, embeddings, conversations, and app data. Schema ships as versioned SQL migrations applied by `python -m persistence.migrate` (psycopg) |
| Embeddings | OpenAI `text-embedding-3-large`, truncated to **1536 dims** via the API `dimensions` param — pgvector HNSW caps at 2000 dims, so native 3072 would force sequential scans |
| Keyword search | Postgres full-text (`tsvector` generated column, GIN index, `websearch_to_tsquery` + `ts_rank`) as the sparse half of hybrid — deliberately **not** BM25; see known debt |
| Generation LLM | OpenAI `gpt-5-mini`, streamed via `ChatOpenAI.astream` — cheap, sufficient for grounded extraction over the 5 provided chunks. Also runs the **query gate** and **query rewriter** calls |
| Reranker LLM | OpenAI `gpt-5-nano` — scores the fused candidates as JSON; cheapest reliable scorer wins |
| Eval judge LLM | OpenAI `gpt-5` — deliberately stronger than the generator; runs per eval suite, not per query |
| Corpus files | Private **Supabase Storage bucket** is the source of truth; `DocumentCorpus/` in the repo is the seed copy. Backend mints ~5 min signed URLs; file bytes never pass through the backend |
| PDF extraction | Unstructured `hi_res` (local CV layout models) — tables come out as structured HTML |
| Deploy | Render — backend and frontend. The ingestion container runs **locally**, reading PDFs from the bucket and writing into hosted Supabase |
| Auth | None. The app is open and all conversation history is visible to everyone |
| Repo | One repo, three projects plus scripts: `frontend/`, `backend/`, `ingestion/` (run-locally batch job, not deployed), `scripts/` |

## Chunking and ingestion — three passes, structure-aware

```
PDF ──► pass 1: extract ──► pass 2: carve ──► pass 3: split ──► embed ──► reconcile
        hi_res layout       section titles     only what is             │
        elements, tables    + tables, alike    still too large     ┌────┴────┬─────────┬────────┐
        grouped, boiler-    topics grouped     ~1500ch, 150 ov.  new │ changed │ unchanged │ removed
        plate removed       tightly                             insert│  diff   │   skip    │ delete
```

**Pass 1 — extraction.** Unstructured `hi_res` turns the PDF into typed, ordered text
elements rather than a wall of characters. Tables survive as structured HTML instead of
being flattened, and page furniture and boilerplate are dropped. *Rejected:*
pypdf/pdfplumber — they shred the dosage and interaction tables where these answers live.

**Pass 2 — section carving.** A custom carver splits along PLR section titles and table
boundaries, so a chunk is a topic rather than a window. Alike material stays tightly
grouped, and the section number and title become the citation. This is the pass that makes
the deliverable a *citation* rather than a chunk.

**Pass 3 — recursive split, only where needed.** Sections and tables that still exceed the
budget get a recursive split with slight overlap; anything that fits stays whole. Splitting
happens *inside* a section, so no chunk straddles two citable sections and overlap never
crosses a boundary.

**Sizes.** `CHUNK_TARGET_CHARS = 1500`, chosen off the median section size in this corpus.
`CHUNK_OVERLAP_CHARS = 150`, capped at a quarter of the available budget. `MIN_CHUNK_CHARS
= 400` is a floor under the budget so a long repeated heading cannot shrink chunks to
nothing — small sections are left whole and are never merged. *Rejected:* a naive recursive
split over the whole document — cutting on character count puts boundaries mid-section, so
the section a citation names is wrong. *Rejected:* one chunk per section, uncapped —
sections run from one sentence to thousands of characters, and uneven chunks degrade dense
comparability.

**Idempotency is reconciliation, not de-duplication.** A `documents` registry holds each
file's SHA-256. Byte-identical files skip extraction entirely; changed files diff at chunk
level; deleted files lose their chunks. One transaction per document. *Rejected:*
`ON CONFLICT DO NOTHING` — it prevents duplicates but never deletes, so an edited PDF
leaves stale chunks answering queries forever.

## Embeddings, store, and prompt structure

**Embeddings — `text-embedding-3-large` at 1536 dims.** The large model for the best
semantic separation available, truncated via the API's `dimensions` parameter because
pgvector's HNSW index caps at 2000 dims — native 3072 is storable but unindexable, forcing
a sequential scan on every query. *Considered and rejected:* `halfvec` 16-bit half-vectors,
which would fit more dimensions under the same index ceiling. Overkill at this corpus size,
and it buys precision in a place precision was not the bottleneck. *Rejected:*
`text-embedding-3-small` — the large model is Matryoshka-trained, so its leading 1536 dims
beat the small model at identical storage cost.

**Store — Supabase, doing four jobs.** Postgres with `pgvector` for dense search, the same
tables for typed chunk metadata so a citation is a join rather than a JSON blob lookup,
Postgres full-text (`websearch_to_tsquery` + `ts_rank`) for the sparse half of hybrid
retrieval, and Storage for the corpus PDFs the citations deep-link into. It was the Swiss
army knife of this project: one service, one connection, no cross-store consistency
problem. *Rejected:* a dedicated vector DB beside it — conversations need a relational home
regardless, so a second store buys two systems to sync on every re-ingestion and two places
for metadata to disagree, for no recall win at 17 documents.

**Prompt structure — labelled and exemplified, not prose.** The prompts began as
paragraph-style instructions with few examples, and the model drifted. They are now
explicitly structured: the gate prompt states one labelled clause per verdict
(`personal_advice`, `unsafe`, `off_topic`, `none`), each carrying concrete exemplars and an
explicit boundary case — a question about a drug this corpus may not hold is `"none"`,
because coverage is retrieval's call, not the gate's. The generation prompt separates what
to answer from, what to cite with, and what to do when the excerpts do not cover it.
Scaling this means adding examples, not rewriting prose — and examples are the kind of
thing that can move into the database and be edited without a deploy.

## Corpus

**Modern PLR-format FDA labels from DailyMed**, chosen for their unambiguous wording: PLR
relies on explicit statements over demonstratives and cross-references, which is what makes
an extracted passage still mean the same thing once it is out of its document. Old-format
(non-PLR) labels were removed — they carry no numbered sections and would have required a
second carving strategy for no gain on this task. The set is also large enough to stage
every query shape the assignment asks for: overlap, non-overlap, and cross-document.

| Drug | Documents | Overlap |
|---|---|---|
| warfarin | `Warfarin`, `Warfarin_2`, `Warfarin_3` | **3 sibling labels** |
| apixaban | `Apixaban`, `Apixaban_2` | **2 siblings** |
| bupropion | `Bupropion`, `Bupropion_2` | **2 siblings** |
| digoxin | `Digoxin`, `Digoxin_2` | **2 siblings** |
| escitalopram | `Escitalopram`, `Escitalopram_2` | **2 siblings** |
| venlafaxine | `Venlafaxine`, `Venlafaxine_2` | **2 siblings** |
| amiodarone | `Amiodarone` | single |
| mirtazapine | `Mirtazapine` | single |
| sertraline | `Sertraline` | single |
| trazodone | `Trazodone` | single |

17 documents, 10 drugs. **6 drugs carry sibling labels** from different manufacturers —
near-identical regulatory prose that retrieval must tell apart, which is what makes
*discrimination* the hard problem here rather than recall. **4 are single-source**, giving
unambiguous lookups. **Cross-document questions** are staged on genuinely separate
documents: sertraline § 5.1 + venlafaxine § 5.1 (suicidality by age), warfarin § 7.2 +
amiodarone § 7.2 (interaction from both sides), sertraline § 5.3 + trazodone § 5.5
(bleeding). **Unanswerables** use drugs deliberately kept out — metformin, albuterol,
aspirin.

## Retrieval

```
question ─► gate ── refuse ───────────────────────────────────┐  (fails CLOSED)
         ─► rewrite (standalone + brand→generic)              │  (fails OPEN)
              ├─► dense  (HNSW cosine, top 10) ─┐             │
              └─► sparse (ts_rank, top 10) ─────┴─ RRF k=10 ──┤
                                                  rerank ─────┤  gpt-5-nano, 0–10
                                            score < 3 dropped ┤
                                                    top 5 ────┴─► generate (streamed)
                                                    empty ──────► canned decline

SSE:  sources (mapping FIRST, before any token) → token… → done | error
```

Hybrid retrieval is the one stretch goal, chosen because the domain decides it: a clinician
acting on a near-miss passage is worse than one missing a feature. RRF uses `k = 10`, sized
to the 10-candidate legs rather than inheriting the published 60, which was tuned on TREC
runs ~1000 deep and over 10 candidates spreads scores only 11% — enough that a chunk both
legs found at rank 10 outranked a chunk one leg found at rank 1. *Rejected:* weighted score
blending, since cosine and `ts_rank` scales need a calibration that would itself need evals.

## Failure analysis

**Chunk count trades precision against recall, and the trade is real.** A large returned
chunk count produced very accurate answers and badly lower precision — and cost roughly
**3× the query latency**. It also defeated the point of hybrid: at this corpus size a wide
net meant dense and sparse returned largely the same documents, so the second leg added
nothing. Lowering the count on both legs and gating rerank at a score cutoff inverted it —
lower average accuracy, but a higher proportion of *specifically* correct chunks (one or
two ranked higher, average lower). The cutoff is the tuning knob and has not been swept
beyond the threshold itself.

**Sparse retrieval underperformed dense in most cases and matched it in some**, tracking
query specificity — which makes sense for a corpus this explicit. Dense runs first and
takes the good hits, so sparse largely returns overlap and contributes few net-new chunks
to the final list. A bigger corpus would separate them; so would a different merge strategy
before reranking, rather than fusing two lists that mostly agree.

**Two measurements were measuring nothing**, and no test caught either:

1. **The sparse leg had never returned a row.** `websearch_to_tsquery` joins terms with
   `&`, so a question demanded one chunk containing every lexeme — 18/18 questions returned
   zero rows. Invisible, because an empty leg is a *handled* case in fusion: hybrid degraded
   silently to dense and reported a clean run. Fixed by rewriting `&` → `|`.
2. **Each configuration re-ran the query rewriter**, so 15 of 18 cases searched different
   text per configuration and every delta mixed the toggle under test with LLM variance.

**This retracts an earlier finding, and the retraction is the point.** That run produced a
fluent analysis claiming hybrid *cost* discrimination accuracy — sparse pulling sibling-drug
chunks, rerank keeping them. Impossible: the leg returned nothing. It survived review
because it sounded exactly like a tradeoff a hybrid retriever really makes. *Check whether a
subsystem ran before explaining what it did.*

Within-case failures, unaffected by that confound:

- **Multi-hop collapse** (`synthesis-warfarin-amiodarone`): the amiodarone label names
  warfarin, so its chunks match both entities and take every slot, while warfarin's own
  § 7.2 CYP table is a semantically thin drug list and never surfaces.
- **Numeric precision in tables**: columns conflated (17% serum vs 40% AUC); one invented
  30–50% where the table implies 15–30%.
- **Partial section serving**: sertraline § 5.1 spans 3 chunks; the age-specific one was not
  served. One config honestly declined half the comparison, another overclaimed it.
- **Silent citation drift**: 18 of 64 answers wrote `[S1]` not `[[S1]]` — and scored
  *grounding clean*, because tags that never parsed cannot be flagged unresolved.

**No run yet exists with a working sparse leg, `k=10`, top-5, and the threshold.** Every
retrieval metric here describes dense-only retrieval, whatever it was labelled.

## What another week buys

**Scaling to 10,000 documents.** Ingestion has to go multi-threaded, with lighter LLM calls
or per-drug batched document operations — it is currently one document at a time. Larger
chunk counts would help recall at that size, but same-drug labels cluster tightly in vector
space, so plain k-nearest starts returning near-duplicates; that wants a different
neighbour strategy — searching from chunks paired with known cross-contaminating drugs or
situations, or a per-document quota before fusion. `ts_rank` also stops being adequate and
wants a real BM25 index.

**Cost.** Query-time LLM calls are deliberately split per tool — the rewriter and the
validity gate are two separate calls. At scale some of those merge into one call to save
time and money. Reranking currently uses a small OpenAI model; a purpose-built reranker or
a fine-tuned semantic matcher would be cheaper and faster at volume. **Caching is the
obvious lever and I would decline it here** — this is a medical setting, and serving a
cached vector search is a correctness risk I would not take to buy latency. Safety first.

**Latency.** This is a real problem, not a theoretical one. Several LLM checks and vector
queries could fire concurrently, but some gate the others, so firing everything at once
raises cost on queries that would have short-circuited. That is the actual budget question:
pay for speculative work, or keep the gates.

**Security.** The query safety check should run on a model from a different vendor
entirely, not another OpenAI model. Cross-referencing two independent models is worth more
than a second opinion from the same family.

**Multi-tenancy** is its own project. There are no accounts at all right now — conversation
history is global and shared. It means a tenant column on `documents`, row-level tenancy on
the conversation tables, and RLS enforcement rather than application-code checks.

## Known shortcuts and technical debt

- **No DB-backed retrieval test.** The suite is hermetic and touches no Postgres — exactly
  why the empty sparse leg survived. The most expensive gap here, and not closed.
- **`k=10` and `candidate_limit=10` are unmeasured.** The threshold sweep replays stored
  scores and is sound; the candidate count changes what is retrieved in the first place.
- **Nothing counts sentinel drift** — the lenient reader makes it harmless *and*
  unobservable, the same trap in a new place.
- The gate and rewriter still call the OpenAI SDK directly, off the one-client rule.
- The frontend **casts** API responses instead of validating them.
- The sparse leg is `ts_rank`, not BM25 — no length normalization, no term saturation.
- No auth, no caching, no live LLM-judge.
