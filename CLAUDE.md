# CLAUDE.md

## DESIGN.md — keep it current

`DESIGN.md` is the design deliverable and the source of truth for project design: the
current stack, feature scope, architecture, and behavior, alongside the tradeoffs that
were rejected, the eval failure analysis, next steps, and known debt. **This file
(`CLAUDE.md`) does not duplicate any of it** — read `DESIGN.md` for design facts. If the
two ever disagree, `DESIGN.md` is right and `CLAUDE.md` needs fixing.

It is **edited in place** and describes the present state, not the order things arrived
in. Rewriting a section so it matches reality is correct; leaving a stale section beside a
new one is not.

Update it in the same working session whenever any of these changes:
- the stack — a library, service, provider, or deployment target added, swapped, or dropped
- feature scope — something added, cut, or deferred
- architecture — the retrieval pipeline, ingestion, storage schema, or API surface
- app behavior — grounding, refusal paths, citations, streaming
- what the eval suite shows breaking, or a failure mode fixed
- a shortcut or piece of technical debt is taken

**It is capped at 1–2 pages.** It is an overview document: diagrams and main points with
their reasoning, not an exhaustive account. When something new has to go in, decide what
comes out — do not let it grow past the cap.

Also refresh its **Last updated** line on every edit. Format is
`YYYY-MM-DD HH:MM ±HH:MM`, minute precision, local time with UTC offset. Read the real
clock with `Get-Date -Format "yyyy-MM-dd HH:mm K"` — never estimate it and never carry
forward an earlier timestamp.

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

### Commit authorship
Author and commit everything as the repository owner (the configured git user). Do not
mention the agent anywhere in git history: no `Co-Authored-By` trailers, no "Generated
with Claude Code" lines, and no AI attribution in commit messages, branch names, tags,
or PR descriptions. AI usage is disclosed in `AI_USAGE.md`, not in git history.

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
