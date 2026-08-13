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
| Auth | None. Explicit choice for time scoping. The app is open and all conversation history is visible to everyone |
| Repo | One repo, three projects plus scripts: `frontend/`, `backend/`, `ingestion/` (run-locally batch job, not deployed), `scripts/` |

## Chunking and ingestion — three passes, structure-aware

```
PDF ─► 1. extract ─► 2. carve ─► 3. split ─► embed ─► reconcile
       hi_res model   section      only what           new│changed│unchanged│removed
       elements,      titles +     is still too     insert│ diff  │  skip   │ delete
       tables kept    tables       large
       grouped
```

1. **Extract.** Unstructured `hi_res` turns the PDF into structured text elements, keeping
   tables grouped together and dropping boilerplate.
2. **Carve.** A custom carver splits along section titles and table boundaries, keeping
   alike topics tightly grouped. The section number and title become the citation.
3. **Split.** Any section or table still too large to stand as one chunk gets a recursive
   split with slight overlap. Splitting stays inside a section, so no chunk straddles two
   citable ones.

`CHUNK_TARGET_CHARS = 1500`, off the median section size; `CHUNK_OVERLAP_CHARS = 150`;
`MIN_CHUNK_CHARS = 400` as a floor under the budget so a long repeated heading cannot shrink
chunks to nothing. *Rejected:* recursive splitting alone — cutting on character count puts
boundaries mid-section, so the section a citation names is wrong, and it shreds the tables
where these answers live.

**Idempotency is reconciliation.** A `documents` registry holds each file's SHA-256:
identical files skip extraction, changed files diff at chunk level, deleted files lose their
chunks, one transaction per document. *Rejected:* `ON CONFLICT DO NOTHING` — it prevents
duplicates but never deletes, so an edited PDF leaves stale chunks answering queries.

## Embeddings, store, and prompts

**`text-embedding-3-large` at 1536 dims** — the large model for the best semantic
extraction, capped at 1536 to stay inside pgvector's 2000-dim index ceiling. *Considered:*
16-bit `halfvec` half-vectors to carry more meaning under the same ceiling — overkill at
this corpus size.

**Supabase was the Swiss army knife of this project.** `pgvector` for dense search, simple
data tooling and easy metadata handling for the typed chunk columns a citation joins
against, `websearch_to_tsquery` for sparse retrieval alongside dense, and a Storage bucket
for the documents themselves — it was right there. *Rejected:* a dedicated vector store
beside it, which buys a second system to keep in sync for no recall win at 17 documents.

**Prompts** were originally paragraph-esque with few examples. They are now clearly
structured with plenty of provided examples for the judge and gate prompts to reason
against. Extending them at scale means adding examples, not rewriting prose — and examples
can move into the database.

## Corpus

**PLR medication labels**, chosen for unambiguous wording and semi-standard document
structure: PLR relies on explicit statements rather than demonstratives, which matters when
a passage has to still mean the same thing outside its document. Large enough to stage every query shape the assignment requires —
overlap, non-overlap, and multi-document. Old-format non-PLR labels were removed as
unneeded complexity for this task.

| Drug | Documents | |
|---|---|---|
| warfarin | `Warfarin`, `Warfarin_2`, `Warfarin_3` | **3 siblings** |
| apixaban | `Apixaban`, `Apixaban_2` | **2 siblings** |
| bupropion | `Bupropion`, `Bupropion_2` | **2 siblings** |
| digoxin | `Digoxin`, `Digoxin_2` | **2 siblings** |
| escitalopram | `Escitalopram`, `Escitalopram_2` | **2 siblings** |
| venlafaxine | `Venlafaxine`, `Venlafaxine_2` | **2 siblings** |
| amiodarone · mirtazapine · sertraline · trazodone | one label each | single-source |

17 documents, 10 drugs. The 6 sibling groups are near-identical prose retrieval must tell
apart — which makes discrimination, not recall, the hard problem. Cross-document questions
run on separate documents (sertraline + venlafaxine § 5.1; warfarin + amiodarone § 7.2;
sertraline § 5.3 + trazodone § 5.5). Unanswerables use drugs kept out: metformin,
albuterol, aspirin.

## Retrieval

```
question ─► gate ── refuse ──────────────────────────────┐  (fails CLOSED)
         ─► rewrite                                      │  (fails OPEN)
              ├─► dense  (HNSW cosine, top 10) ─┐        │
              └─► sparse (ts_rank, top 10) ─────┴ RRF ───┤
                                          rerank, cut <3 ┤
                                                  top 5 ─┴─► generate (streamed)
                                                  empty ───► canned decline
```

Hybrid retrieval is the one stretch goal. RRF uses `k = 10`, sized to the 10-candidate legs
rather than inheriting the published 60, which was tuned on lists ~1000 deep and over 10
candidates leaves rank nearly meaningless. *Rejected:* weighted score blending — cosine and
`ts_rank` scales need a calibration that would itself need evals.

## Failure analysis

**Chunk count trades precision against accuracy.** Too large a count lowered precision
greatly while giving very accurate answers, took ~3× as long per query, and — at this corpus
size — stopped dense and sparse returning different documents at all. Lowering the returned
count on both legs and gating rerank at a score cutoff gave less accurate results on
average but a higher proportion of specifically correct chunks: one or two ranked higher,
the average lower. The cutoff is the knob to fine-tune.

**Sparse fetching underperformed dense in most cases and was even in some**, tracking query
specificity, which fits a corpus this detailed. Dense runs first and takes the good hits, so
sparse largely returns overlapping chunks and contributes few to the final list. A bigger
corpus or a different merge strategy before reranking would fix it.

**Two measurements were measuring nothing.** The sparse leg had never returned a row —
`websearch_to_tsquery` joins terms with `&`, so a question demanded one chunk holding every
lexeme, and 18/18 returned zero. It was invisible because an empty leg is a handled case in
fusion. Separately, each eval configuration re-ran the rewriter, so 15 of 18 cases searched
different text per configuration. This retracts an earlier finding that hybrid retrieval
cost discrimination accuracy — impossible, since the leg returned nothing.

Remaining within-case failures: **multi-hop collapse** (the amiodarone label names warfarin,
so its chunks take every slot and warfarin's own § 7.2 table never surfaces); **numeric
precision in tables** (columns conflated, one invented dose range); **partial section
serving** (sertraline § 5.1 spans 3 chunks, the needed one unserved); **citation drift** (18
of 64 answers wrote `[S1]` not `[[S1]]`, and scored grounding-clean because unparsed tags
cannot be flagged).

**No run yet exists with a working sparse leg, `k=10`, top-5, and the threshold.**

## What another week buys

- **Ingestion at scale** — multi-threaded, with lighter LLM calls or batch document
  operations grouped by drug.
- **Retrieval at scale** — larger chunk counts help a larger corpus but cluster tightly,
  since same-drug documents are so similar. That wants neighbour strategies beyond
  k-nearest: searching from chunks combined with known cross-contaminating drugs or
  situations.
- **Cost** — query calls are split per tool (rewriting and the validity gate are two
  separate calls); some could group into one. Reranking uses a small OpenAI model, where a
  dedicated reranker or fine-tuned semantic matching would be cheaper at scale.
- **Latency** — a real issue. Multiple LLM checks and vector queries could run at once, but
  some gate the others, so firing everything costs more than letting the gates short-circuit.
- **Caching** — probably a bad idea in a medical setting. I would take the cost and speed
  penalty at scale instead. Safety first.
- **Security** — the query check should be a different model from OpenAI altogether, for
  cross-referencing.
- **Multi-tenancy** — its own fish to fry. There are no accounts at all right now.

## Known shortcuts and technical debt

- **No DB-backed retrieval test** — the suite is hermetic and touches no Postgres, which is
  exactly why the empty sparse leg survived.
- **`k=10` and `candidate_limit=10` are unmeasured** — the threshold sweep replays stored
  scores; the candidate count changes what is retrieved in the first place.
- **Nothing counts sentinel drift** — the lenient reader makes it harmless and unobservable.
- **The suite no longer tests discrimination.** Sibling labels are what make this corpus
  hard, and the traps that measured it were cut; the scorer still supports them, so the
  report's discrimination row now reads `n/a`. Three off-topic cases are also filed as
  `unanswerable`, which the gate refuses differently, so they report as failures.
- The gate and rewriter still call the OpenAI SDK directly, off the one-client rule.
- The frontend casts API responses instead of validating them.
- Uses LangChain where unneeded (tech debt).
- Flat file structure and functions (tech debt).
- The sparse leg is `ts_rank`, not BM25.
- No auth, no caching, no live LLM-judge.
- Links repeat in responses, and some responses describe chunks when not needed.
