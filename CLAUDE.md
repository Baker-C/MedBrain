# CLAUDE.md

## Living Documents — Keep These Updated

Three markdown files at the repo root are yours to maintain. They split by purpose:

| File | Holds | Style |
|---|---|---|
| `DESIGN.md` | The design **as it is now** — source of truth | Edit in place |
| `DESIGN_RECORDS.md` | **Why** each choice was made, and what was rejected | Append-only |
| `AI_USAGE_RECORDS.md` | Where AI output was overridden, corrected, or rejected | Append-only |

### DESIGN.md — the source of truth for project design

`DESIGN.md` holds the current stack, feature scope, architecture, and behavior. **This
file (`CLAUDE.md`) does not duplicate any of it** — read `DESIGN.md` for design facts. If
the two ever disagree, `DESIGN.md` is right and `CLAUDE.md` needs fixing.

Unlike the records files, `DESIGN.md` is **edited in place**. It describes the present
state, not the order things arrived in. Rewriting a section so it matches reality is
correct; leaving a stale section beside a new one is not.

Update `DESIGN.md` in the same working session whenever any of these changes:
- the stack — a library, service, provider, or deployment target added, swapped, or dropped
- feature scope — something added, cut, or deferred
- architecture — the retrieval pipeline, ingestion, storage schema, or API surface
- app behavior — grounding, refusal paths, citations, streaming
- one of its open questions gets decided
- a shortcut or piece of technical debt is taken

Also refresh its **Last updated** timestamp on every edit, in the format below.

Note `DESIGN.md` doubles as a graded deliverable capped at 1–2 pages. It will run longer
than that while it serves as the working source of truth; it gets trimmed to the graded
shape near the end. Do not trim it early to hit the page count.

### The records files

`DESIGN_RECORDS.md` and `AI_USAGE_RECORDS.md` are append-only running records of what
happened while this codebase was built. Append to the relevant file in the same working
session as the change — do not defer it. Do not rewrite or delete past entries; add a new
entry that supersedes an old one.

The division of labor with `DESIGN.md`: a decision changes `DESIGN.md` to the new state
*and* adds a `DESIGN_RECORDS.md` entry explaining the choice and what lost. `DESIGN.md`
answers "what is it"; the records answer "why, and what else was on the table".

### Timestamps — required on every entry for *_RECORDS.md files

Every entry in both files carries one timestamp, directly under its heading:

```
**Timestamp:** 2026-08-11 21:31 -07:00
```

Format is `YYYY-MM-DD HH:MM ±HH:MM`, minute precision, local time with UTC offset. Read
the real clock with `Get-Date -Format "yyyy-MM-dd HH:mm K"` — never estimate it and never
carry forward a timestamp from an earlier entry.

The single timestamp represents **both** when the decision was made and when it was
recorded. Those are the same moment because entries are appended in the same working
session as the change. If they ever diverge — a decision recorded later than it was made —
say so in the timestamp line rather than presenting the recording time as the decision
time:

```
**Timestamp:** 2026-08-11 21:31 -07:00 (decision made ~19:00, recorded late)
```

Do not fabricate precision. If a timestamp is approximate, mark it approximate.

`DESIGN.md` uses the same format for its single **Last updated** line, which is replaced
on every edit rather than appended to.

### DESIGN_RECORDS.md

Record, as they happen:

1. **Architectural decisions and rejected tradeoffs** — chunking strategy and size,
   embedding model, vector store, retrieval approach, prompt structure. For each, record
   what was chosen, what was rejected, and why that fits this corpus and use case.
2. **Failure analysis from the eval suite** — what the evals show breaking, and why.
3. **Next steps** — scaling to 10,000 documents, multi-tenancy, cost controls, latency
   budgets.
4. **Known shortcuts and technical debt** — what was skipped on purpose given the time
   box.

Append to DESIGN_RECORDS.md when you:
- choose or change a chunking strategy, chunk size, or overlap
- choose or change the embedding model, vector store, or retrieval approach
  (dense/hybrid/rerank, top-k, filters)
- change the prompt structure or context assembly
- reject an alternative that was seriously considered — record the rejection, not only the
  winner
- run the eval suite and see a new failure mode, or fix one
- take a shortcut that would not ship — add it to the debt list immediately, while the
  reason is still fresh

### AI_USAGE_RECORDS.md

> **Note:** Before a new push to remote, check the changes recorded here. If any of those
> changes happened during that commit, record that commit next to the code diff.

Record, as they happen:

1. **Which AI tools were used, and for what.**
2. **Concrete examples where AI-generated output was overridden, corrected, or rejected.**

Append to AI_USAGE_RECORDS.md when you:
- start using a new AI tool on this project
- override, rewrite, correct, or reject AI-generated output for a real reason — log it at
  that moment

Every logged override / rewrite / rejection has exactly three parts:

1. **What it ended up as** — one short sentence naming the thing. Examples:
   "k-nearest-neighbors function", "Chroma upsert function", "chunk size logic",
   "feature file structure".
2. **The change and the reasoning** — state it as *this → that*: what the AI produced,
   what it became, and why the user chose to change it (if they said, or if it is
   knowable). Write enough detail that the decision can be defended later even if the
   change was fully overridden and none of the original code survives anywhere.
3. **The code diff and its commit** — the actual diff of the change, and next to it the
   commit in the history that carries it. If the change is not yet committed, leave the
   commit field pending and fill it in at the pre-push check above.

## Project Context

**MedBrain** — a web app that answers a clinical operations professional's
natural-language questions over a corpus of public medical documents with grounded, cited
answers. A document-lookup tool for professionals, not a source of medical advice.

Two files hold the project truth, and this file deliberately holds none of it. Read them
rather than assuming:

- **`DESIGN.md`** — the current design: stack, feature scope, architecture, app behavior,
  open questions, and known debt. Read it before writing code or making a design decision.
- **`take-home-assignment-fullstack-ai.md`** — the assignment, and the source of truth for
  **project requirements and grading**. Read it before any scope decision: what must be
  built, what is explicitly not graded, and where the weight sits.

The assignment defines the requirement; `DESIGN.md` records how this project chooses to
satisfy it. If `DESIGN.md` ever contradicts a requirement, that is a bug in `DESIGN.md` —
say so rather than following it.

## Rules

These rules have no priority order. Apply all of them.

### Error handling
Add error handling only where a failure is realistic and unhandled failure would be
confusing. Do not wrap code in `try`/`catch` defensively. Do not validate inputs that
the calling code already guarantees. Let unexpected errors surface with their real stack
trace.

### Extract logic into named functions
Break logic into small named functions with one responsibility each. Do not write long
sequential blocks of inline logic. Keep logic inline only when splitting it would hide
the flow rather than clarify it (for example, three lines that are meaningless apart).
Name each function after what it produces or decides.

### Reuse existing utilities
Before you write a helper, search the codebase for one that already does the job and use
it. When you find the same logic in two places, move it into a shared util and have both
callers use it. Put new shared helpers with the existing utils, not next to one caller.

### Optimize for readability, not production hardening
This is a demo project. Its purpose is to let a reader follow the code end to end and
see the logic clearly. Write the simplest version that works. If a shorter version does
the same thing, write the shorter version.

**Build these — they are graded deliverables:**
- **Tests** — a handful of meaningful unit/integration tests covering the paths that
  matter. Pick the right tests, not many tests. Coverage is explicitly not graded.
- **CI on push** — one workflow that runs lint, type checks, and those tests. Nothing
  more.
- **Type annotations** — type the code and keep the type checker clean.
- **User-facing error and loading states** — the UI handles a failed or slow request
  gracefully, including mid-stream failures, and the API returns usable errors.

**Do not build these unless the user explicitly asks or agrees to it first:**
retry/backoff logic, logging or tracing layers, observability tooling, config systems,
abstractions for a single use, and performance work. Going past the list above is
gold-plating and costs points.
