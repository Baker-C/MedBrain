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

**AI Proposal:** run `RecursiveCharacterTextSplitter` over the whole document at a fixed size.

**Personal Decision:** three passes — layout-aware extraction, then carve into real sections
along titles and table boundaries, then recursive split only what is still too large.

**Why:** the deliverable is a *citation*, not a chunk. Splitting on character count puts
section boundaries mid-chunk, so the section a citation names is wrong, and it shreds the
dosage and interaction tables that hold most of these answers.

### 2. The one that cost the most, and that review did not catch

**AI Produced:** the sparse retrieval leg, as
`where tsv @@ websearch_to_tsquery('english', %s)`.

**Personal Correction:** the same query with the compiled tsquery's `&` operators rewritten
to `|`.

**Why:** valid SQL that reads correctly and passed my review, but `websearch_to_tsquery`
joins bare terms with `&`, so a whole question became a conjunction no chunk satisfies —
**zero rows on all 18 eval questions**, and the stretch goal was being graded on a leg that
never ran.

**The AI missed it because nothing in its field of view could show it.** The bug is not in
code that errors, and an empty leg is a handled case downstream, so fusion quietly fell back
to dense-only and reported a clean run. Lint, types, and a hermetic suite all check code
against itself; this failure only exists against a live index.

**I caught it by reading the output instead of the code** — the fused scores clustered far
too tightly for two independent rankings, and the served chunks turned out to be 126 of 128
dense-only. The same blind spot had already produced a fluent failure analysis crediting the
sparse leg with results it never returned. A plausible causal story is worth nothing until
you check that the subsystem ran at all.

### 3. Gate and rewriter

**AI Proposal:** one combined LLM call behind a single on/off request parameter.

**Personal Decision:** two independently toggled tools, each with its own prompt and its own
failure direction, composed by the pipeline.

**Why:** one call cannot express two failure directions, and these need opposite ones — the
gate fails **closed** (a broken safety check refuses rather than answers ungated), the
rewriter fails **open** (a broken rewriter never blocks a question). Making the rewriter a
separately toggled stage is also what exposed a second harness bug alongside §2: it was
re-running inside every eval configuration, so 15 of 18 cases were searching different text.

### 4. Eval harness

**AI Proposal:** a script under `scripts/` driving the deployed query endpoint's trace mode
over HTTP.

**Personal Decision:** `backend/eval/`, running in-process against `prepare_turn()` — the same
function the query endpoint composes its response from.

**Why:** the harness must not require a running backend. It also stays typed end to end
instead of parsing JSON back into restated shapes, and there is now exactly one answer
path rather than a graded one and a measured one free to drift apart.

### 5. Ingestion location

**AI Proposal:** keep it at `backend/ingestion/`, with the heavy CV dependencies isolated in a
non-default dependency group.

**Personal Decision:** its own top-level project with its own lockfile, Dockerfile, and tests.

**Why:** ingestion is never reached through the API, so it does not belong inside the API
project. A separate lockfile also makes the lean-backend property structural rather than
procedural — the serving image *cannot* resolve the extraction dependencies at all.
