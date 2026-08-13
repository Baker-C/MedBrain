# AI_USAGE.md

**Tool:** Claude Code (Anthropic CLI, Opus 5), used throughout — design interrogation,
scaffolding, implementation, refactors, and drafting the eval suite. Every architectural
decision in this repo is mine; the AI's job was to argue, implement, and be overruled.

Two supporting notes. The 18 eval cases in `backend/eval/suite.py` were **drafted** by
Claude at my direction rather than hand-written first — disclosed explicitly because the
assignment asks for a set you author yourself. Every expected document, section number,
and answer was verified against extracted label text during drafting, and I reviewed and
took ownership of the set. And several corrections below are **invisible in the git
history**, because branches were committed as authored sequences after the work was
finished, so the corrected form is what reached a commit. That is precisely why this
record exists.

Six places I overrode the model, and what each was worth.

---

**1. Structure-aware carving before recursive splitting — not recursive splitting alone.**
The proposed chunker was the standard one: run `RecursiveCharacterTextSplitter` over the
whole document at a fixed size. I rejected it and specified two passes — parse the PDF
with a layout-aware extractor, carve it into real PLR sections from their numbered
headings, pull tables out as atomic blocks, *then* run the recursive splitter inside each
section. The reason is that the deliverable is a **citation**, not a chunk: a splitter
that cuts on character count puts section boundaries mid-chunk, so the section a citation
names is ambiguous or simply wrong, and it shreds the dosage and interaction tables that
are where these answers actually live. The two-pass order gets both properties at once —
structure decides the boundaries, size decides only the subdivision — and overlap exists
only *within* a section, so no chunk can straddle two citable ones. It is the single
decision the whole grounding story rests on.

**2. Two independent toggles, then two separate tools — which is what exposed a broken
eval harness.** The proposal was one combined gate-and-rewrite LLM call behind a single
on/off parameter. I split it twice: first into two independent booleans each owning its
own prompt, then into two self-contained tools composed by the pipeline — the combined
module was named for its *position* rather than what it does, and it was doing the
pipeline's job. Two payoffs, both unavailable from the combined version. It bought
**per-tool failure semantics**: the gate fails *closed* (a broken safety check refuses
rather than answers ungated), the rewriter fails *open* (a broken rewriter never blocks a
question) — one call cannot express both directions. And it made the rewriter a visible,
independently-toggled stage, which is how I caught that the harness re-ran the rewriter
inside every configuration: 15 of 18 cases were searching *different text* per
configuration, so every "before/after" number the stretch goal is graded on was mixing the
toggle under test with LLM variance. Fixed by rewriting once per case and reusing it.

**3. The eval harness runs in-process, not over HTTP.** The plan I was handed put the
harness in `scripts/` driving the deployed query endpoint's trace mode over HTTP. I
rejected the premise: the harness must not require the backend to be running. It became
`backend/eval/`, importing `prepare_turn()` — the same function the query endpoint
composes its response from. This is the highest-leverage override in the project. It takes
the web layer off the critical path of the assignment's heaviest-weighted deliverable,
keeps the harness typed end to end instead of parsing JSON back into restated shapes, and
guarantees there is exactly one answer path rather than a graded one and a measured one
free to drift apart.

**4. Retrieval restructured into pipeline-stage packages.** The AI had built nine flat
modules in `retrieval/tools/`, applying my own earlier "each tool is self-contained"
convention literally — and applying it to things that were not tools. One file had
accumulated a SQL fragment, a row reader, and a domain type; the pipeline's public return
type was defined inside a leaf tool. It wrote those files that way across two sessions and
never flagged the mismatch. I caught it on inspection, asked for a plan rather than an
immediate change, and chose the deepest of three options: retire `tools/` for folders named
after the pipeline stages — `query/` → `search/` → `ranking/` — accepting that this
supersedes a convention I set myself. Shipped as a rename-only diff, tests green either
side (`6e6fd89`).

**5. Ingestion is its own top-level project, not a backend package.** The proposal kept it
at `backend/ingestion/` with the heavy CV extraction dependencies isolated in a non-default
dependency group — one toolchain, and the backend image just skips the group. I rejected
the premise rather than the mechanism: ingestion is never reached through the API, so it
does not belong inside the API project; if it ever needs exposing it becomes its own
service. It got its own `pyproject.toml`, lockfile, Dockerfile, and tests. The AI agreed on
review and added an argument I had not made — a separate lockfile makes the lean-backend
property *structural* rather than procedural, since the backend image then cannot resolve
the extraction dependencies at all. It also pushed back on one part and I took it: the
schema keeps a single owner in `backend/persistence/migrations/`.

**6. The relevance threshold was measured, not picked.** I asked for a minimum score
"right in the middle of avg outputs". The AI's move was to resolve my ambiguous number into
a plausible one — normalize it against the 0–10 rerank scale, get 7, implement it. I
rejected that and required it be swept against the saved traces first, which carry
`rerank_score` for all 128 served chunks of a real run and cost nothing to replay. The
sweep showed 7 would have cost 8 points of strict Recall@5 and darkened a working synthesis
case, while **3** — the median of a strongly bimodal distribution — is the tightest cut
with no recall loss at all. The number was sitting in the repository the whole time; the
failure mode was reaching for a defensible-*sounding* constant instead of the data already
on disk. I also rejected two implementations that mapped an *unscored* chunk to a failing
score: `rerank_score` is None both when the reranker is off and when its call failed open,
so either version would have let one unreachable OpenAI call turn every query in the app
into a false claim that the corpus does not cover it (`99edc1a`).

---

**The one that cost the most, and was not caught by review.** The AI wrote the sparse
retrieval leg as `where tsv @@ websearch_to_tsquery('english', %s)`. Valid SQL, reads
correctly, passed my review — and it returned **zero rows for all 18 eval questions**,
because `websearch_to_tsquery` joins bare terms with `&`, making a whole question a
conjunction no chunk satisfies. It was invisible from the application side: an empty leg is
a documented, handled case in fusion, so hybrid retrieval degraded silently to dense-only
and reported a clean full run. Nothing in lint, mypy, or the hermetic test suite could see
it — the bug was not in code that errors, and its failure mode is indistinguishable from a
legitimate empty result. I found it by asking why the fused scores clustered so tightly and
then checking which leg the served chunks came from: 126 of 128 were dense-only. The
stretch goal had been graded on a leg that never ran.

Worse, the AI had already written a failure analysis explaining that hybrid retrieval *cost*
discrimination accuracy — the sparse leg pulling sibling-drug chunks on shared vocabulary,
the reranker keeping them, presented as the honest cost of the stretch goal. Fluent,
plausible, and impossible: the leg returned nothing. It survived because it sounded exactly
like a tradeoff a hybrid retriever really does make. Both the SQL and the false reading are
corrected, and the standing lesson is in `DESIGN.md`: **check a causal story about a
subsystem against whether that subsystem ran at all.**
