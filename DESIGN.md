# DESIGN.md — MedBrain

**Last updated:** 2026-08-12 18:58 -07:00 · Live: <https://medbrain-site.onrender.com/>

Grounded, cited answers over **17 FDA drug labels from DailyMed** for a clinical
operations professional. A document-lookup tool, not a source of medical advice.

Corpus choice drives everything below: all 17 are modern **PLR-format** labels with
numbered sections 1–17, and 6 of the 10 drugs have 2–3 sibling labels from different
manufacturers. Uniform structure makes one carving strategy sufficient; sibling labels
make *discrimination* the hard retrieval problem rather than recall.

## System

```
  React/TS  ──HTTP+SSE──►  FastAPI  ──►  Supabase Postgres + pgvector
  (Render)                 (Render)      chunks · embeddings · tsvector · conversations
                              │                        ▲
                              └──► OpenAI              │  (writes)
                                                 ingestion container
   Private Storage bucket ─────────────────────►  (runs locally, never deployed)
   17 PDFs · signed URLs for citation click-through
```

Keys stay server-side; the frontend receives only an API URL. Ingestion is a separate
project with its own lockfile, so the serving image *cannot* resolve the CV extraction
dependencies.

## Ingestion — repeatable and idempotent

```
bucket → hi_res extract → clean → carve sections → split ~1500ch → embed → reconcile
                                  (pass 1)         (pass 2)                    │
                                                                    ┌──────────┴──────────┐
                                                            new │ changed │ unchanged │ removed
                                                          insert │ diff    │ skip      │ delete
```

**Idempotency is reconciliation, not de-duplication.** A `documents` registry holds each
file's SHA-256. Byte-identical files skip extraction entirely; changed files diff at chunk
level; deleted files lose their chunks. One transaction per document.

**Chunking is two-pass because the deliverable is a citation, not a chunk.** Pass 1 carves
real PLR sections from numbered headings and lifts tables out whole; pass 2 splits *inside*
a section, so no chunk straddles two citable sections and overlap never crosses a boundary.

## Retrieval + generation — the stretch goal is hybrid retrieval

```
question
   │
   ├─► gate ──── refuse ──────────────────────────────────────┐  (fails CLOSED)
   ├─► rewrite (standalone + brand→generic)                   │  (fails OPEN)
   │      │                                                   │
   │      ├──► dense  (HNSW cosine, top 10) ──┐               │
   │      └──► sparse (ts_rank, top 10) ──────┴─► RRF k=10 ──►│
   │                                                rerank ───┤  gpt-5-nano, 0–10
   │                                          score < 3 drop ─┤
   │                                              top 5 ──────┤
   │                                                          ▼
   └──────────────────────────────────────────►  empty? ─► canned decline
                                                    else ─► generate (streamed)

   SSE:  sources (mapping FIRST, before any token) → token… → done | error
```

Chosen because the domain decides it: a clinician acting on a near-miss passage is a worse
outcome than one missing a feature, so the single stretch slot buys retrieval precision.

Everything except dense search is an independent toggle on a frozen config passed in
explicitly — which is what lets the eval harness sweep configurations in one session.

## Key decisions and rejected tradeoffs

| Area | Chosen | Rejected, and why |
|---|---|---|
| **Vector store** | Supabase Postgres + `pgvector` | *Dedicated vector DB (Qdrant/Chroma/Pinecone):* conversations need a relational home anyway, so a second store buys two systems to sync per re-ingestion and two places for metadata to disagree — for no recall win at 17 docs. One store also means both legs fuse in one connection. |
| **Chunking** | Two-pass: section carve → ~1500-char split within section | *Naive recursive split over the whole doc:* cutting on character count puts boundaries mid-section, so the section a citation names is wrong, and it shreds dosage/interaction tables. *One chunk per section:* sections run from one sentence to thousands of chars; uneven chunks degrade dense comparability. |
| **Extraction** | Unstructured `hi_res` (layout CV) | *pypdf/pdfplumber:* flattens tables into word soup, and tables are where these answers live. |
| **Embedding** | `text-embedding-3-large` @ **1536** dims | *Native 3072:* pgvector HNSW caps at 2000 — storable but unindexable, so every query becomes a sequential scan. *`-3-small`:* the large model is Matryoshka-trained, so its leading 1536 dims win at identical storage cost. |
| **Fusion** | RRF, **k = 10** | *k = 60 (the published default):* tuned on TREC runs ~1000 deep. Over 10 candidates it spreads scores 11%, so a chunk both legs found at rank 10 beat one leg's rank 1 — fusion became a vote-counter. *Weighted blending:* cosine and `ts_rank` scales need a calibration that would itself need evals. |
| **Rerank** | Self-built pointwise LLM, **sorted in code** | *Cross-encoder:* torch in the serving image. *Hosted rerank API:* a second vendor. *Listwise:* a returned permutation can silently drop ids; pointwise maps 1:1 and leaves a numeric trace. |
| **Threshold** | `rerank_score >= 3` | *7 (a plausible-sounding number):* swept against 128 real scored chunks — 7 costs 8 points of Recall@5; 3 is the tightest cut costing nothing. An *unscored* chunk passes, so one failed rerank call can't blank the app. |
| **Prompt structure** | Excerpts tagged `[[S1]]`; mapping streamed first; **no conversation history** in the generation prompt | *Model emits citations itself:* it would invent them. *History in-prompt:* an ungrounded prior turn competes with the label for attention — the rewriter makes follow-ups standalone instead. Gate returns **one reason**, not three booleans (8 states, 7 undefined precedence rules). |

**The boundary.** Persistent disclaimer banner, plus a gate returning `personal_advice`,
`unsafe`, or `off_topic` — each with its own message. `off_topic` means *outside medicine*,
not *outside the corpus*: a question about a drug we lack is on topic and must reach the
honest not-in-corpus decline. Refusals, empty retrieval, and threshold-filtered-to-zero all
stream through the same canned path, so a decline reaches the client through exactly the
contract a real answer does.

## Failure analysis

`make eval` → 18 authored cases (6 lookup, 1 table, 3 synthesis, 3 discrimination, 3
unanswerable, 2 advice) through `prepare_turn()` — the same function the endpoint uses, so
there is no second path to drift. Strict/lenient lenses × document/section granularity,
behavioral checks, `gpt-5` judge, two configurations.

**Two measurements were measuring nothing, and no test caught either.**

1. **The sparse leg had never returned a row.** `websearch_to_tsquery` joins terms with
   `&`, so a question demanded one chunk containing every lexeme: 18/18 questions returned
   zero rows. Invisible, because an empty leg is a *handled* case in fusion — hybrid
   degraded silently to dense and reported a clean run. Fixed by rewriting `&` → `|`.
2. **Each configuration re-ran the rewriter**, so 15 of 18 cases searched different text
   per configuration and every delta mixed the toggle with LLM variance.

**This retracts an earlier finding, and the retraction is the point.** That run produced a
fluent analysis claiming hybrid *cost* discrimination accuracy — sparse pulling sibling-drug
chunks, rerank keeping them. Impossible: the leg returned nothing. It survived review
because it sounded exactly like a tradeoff a hybrid retriever really makes. *Check whether a
subsystem ran before explaining what it did.*

What held: gate 8/8, unanswerables 12/12, high recall. Grounding scored clean — but see
drift, below, for why that was partly vacuous. Within-case failures, unaffected:

- **Multi-hop collapse** (`synthesis-warfarin-amiodarone`): the amiodarone label names
  warfarin, so its chunks match both entities and take every slot, while warfarin's own
  § 7.2 CYP table is a semantically thin drug list and never surfaces. The textbook case for
  the decomposition goal not chosen; fix is sub-queries or a per-document quota in fusion.
- **Numeric precision in tables**: columns conflated (17% serum vs 40% AUC); one invented
  30–50% where the table implies 15–30%. The judge caught both.
- **Partial section serving**: sertraline § 5.1 spans 3 chunks; the age-specific one wasn't
  served. One config honestly declined half the comparison, another overclaimed it.
- **Silent citation drift**: 18 of 64 answers wrote `[S1]` not `[[S1]]` — and scored
  *grounding clean*, because tags that never parsed can't be flagged as unresolved. Reading
  both forms recovers 66 citations on the same run.

**No run yet exists with a working sparse leg, `k=10`, top-5, and the threshold.** Every
retrieval metric here describes dense-only retrieval, whatever it was labelled. The re-run
is the highest-value next step.

## What another week buys

- **10,000 documents** — `ts_rank` is not BM25; the production answer is a real BM25 index
  in or beside Postgres. Bucket listing pages properly (it currently reads one page). HNSW
  tuning becomes real. Ingestion moves to a queue with per-document workers, which the
  existing per-document transaction boundary already makes safe.
- **Multi-tenancy** — none today. Tenant column on `documents`, row-level tenancy on
  conversations, enforced by RLS rather than application code.
- **Cost** — three LLM calls precede generation; gate and rewrite collapse into one. The
  threshold already skips generation on weak retrieval. Re-ingestion is near-free by design.
- **Latency** — legs run sequentially (first thing to parallelize); the reranker dominates,
  one call over the fused set before a token streams.

## Known shortcuts and technical debt

- **No DB-backed retrieval test.** The suite is hermetic and touches no Postgres — which is
  exactly why the empty sparse leg survived. The most expensive gap here, not closed.
- **`k=10` and `candidate_limit=10` are unmeasured.** The threshold sweep replays stored
  scores and is sound; the candidate count changes what is retrieved at all.
- **Nothing counts sentinel drift** — the lenient reader makes it harmless *and*
  unobservable, the same trap in a new place.
- Gate and rewriter still call the OpenAI SDK directly, off the one-client rule.
- Frontend **casts** API responses instead of validating them.
- No auth; conversation history is global. No caching. No live LLM-judge.
