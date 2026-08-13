# AI_USAGE.md

**Tool:** Claude Code (Anthropic CLI, Opus 5), used throughout — design interrogation,
scaffolding, implementation, refactors, and drafting the eval suite. Every architectural
decision in this repo is mine; the AI's job was to argue, implement, and be overruled.

**Two disclosures.** The 18 eval cases in `backend/eval/suite.py` were *drafted* by Claude
at my direction rather than hand-written first, since the assignment asks for a set you
author yourself. Every expected document, section, and answer was verified against
extracted label text, and I reviewed and took ownership of the set. Separately, several
corrections below are invisible in the git history: branches were committed as authored
sequences after the work was done, so only the corrected form ever reached a commit. That
is why this record exists.

---

### 1. Chunking strategy

**Proposed:** run `RecursiveCharacterTextSplitter` over the whole document at a fixed size.

**Decided:** three passes — layout-aware extraction, then carve into real sections along
titles and table boundaries, then recursive split only what is still too large.

**Why:** the deliverable is a *citation*, not a chunk. Splitting on character count puts
section boundaries mid-chunk, so the section a citation names is wrong, and it shreds the
dosage and interaction tables that hold most of these answers.

### 2. Gate and rewriter

**Proposed:** one combined LLM call behind a single on/off request parameter.

**Decided:** two independently toggled tools, each with its own prompt and its own failure
direction, composed by the pipeline.

**Why:** one call cannot express two failure directions, and these need opposite ones — the
gate fails **closed** (a broken safety check refuses rather than answers ungated), the
rewriter fails **open** (a broken rewriter never blocks a question). Making the rewriter a
separately toggled stage is also what exposed the harness bug in §7: it was re-running
inside every eval configuration, so 15 of 18 cases were searching different text.

### 3. Eval harness

**Proposed:** a script under `scripts/` driving the deployed query endpoint's trace mode
over HTTP.

**Decided:** `backend/eval/`, running in-process against `prepare_turn()` — the same
function the query endpoint composes its response from.

**Why:** the harness must not require a running backend. It also stays typed end to end
instead of parsing JSON back into restated shapes, and there is now exactly one answer
path rather than a graded one and a measured one free to drift apart.

### 4. Retrieval package layout

**Proposed:** nine flat modules under `retrieval/tools/`, applying my own earlier
"self-contained tool" convention literally.

**Decided:** folders named for the pipeline stages — `query/` → `search/` → `ranking/` —
with a shared contract module.

**Why:** the convention was being applied to things that were not tools. One file had
accumulated a SQL fragment, a row reader, and a domain type; the pipeline's public return
type was defined inside a leaf tool. Shipped as a rename-only diff, tests green either side.

### 5. Ingestion location

**Proposed:** keep it at `backend/ingestion/`, with the heavy CV dependencies isolated in a
non-default dependency group.

**Decided:** its own top-level project with its own lockfile, Dockerfile, and tests.

**Why:** ingestion is never reached through the API, so it does not belong inside the API
project. A separate lockfile also makes the lean-backend property structural rather than
procedural — the serving image *cannot* resolve the extraction dependencies at all.

### 6. Relevance threshold

**Proposed:** resolve my ambiguous "middle of the outputs" into a plausible number —
normalize against the 0–10 rerank scale, get 7, implement it.

**Decided:** sweep it against the saved traces first. The answer was **3**.

**Why:** the data was already on disk — 128 scored chunks from a real run, free to replay.
The sweep showed 7 costs 8 points of strict Recall@5 and darkens a working synthesis case,
while 3 is the tightest cut that costs nothing. I also rejected two implementations that
treated an *unscored* chunk as failing: `rerank_score` is None both when the reranker is off
and when its call fails open, so either version would have let one unreachable OpenAI call
turn every query into a false claim that the corpus lacks an answer.

---

### 7. The one that cost the most, and that review did not catch

**Produced:** the sparse retrieval leg, as
`where tsv @@ websearch_to_tsquery('english', %s)`.

**Corrected to:** the same query with the compiled tsquery's `&` operators rewritten to `|`.

**Why:** valid SQL, reads correctly, passed my review — and it returned **zero rows for all
18 eval questions**, because `websearch_to_tsquery` joins bare terms with `&`, making a
whole question a conjunction no chunk satisfies. It was invisible from the application side:
an empty leg is a documented, handled case in fusion, so hybrid retrieval degraded silently
to dense-only and reported a clean full run. Nothing in lint, mypy, or the hermetic tests
could see it — the bug was not in code that errors, and its failure mode is
indistinguishable from a legitimate empty result. I found it by asking why the fused scores
clustered so tightly, then checking which leg the served chunks came from: 126 of 128 were
dense-only. The stretch goal had been graded on a leg that never ran.

Worse, the AI had already written a failure analysis explaining that hybrid retrieval *cost*
discrimination accuracy — the sparse leg pulling sibling-drug chunks, the reranker keeping
them, presented as the honest cost of the stretch goal. Fluent, plausible, and impossible:
the leg returned nothing. It survived because it sounded exactly like a tradeoff a hybrid
retriever really does make. Both the SQL and the false reading are corrected, and the
standing lesson is in `DESIGN.md`: check a causal story about a subsystem against whether
that subsystem ran at all.
