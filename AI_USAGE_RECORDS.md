# AI_USAGE_RECORDS.md

Append-only record of AI tool usage on this project, and of concrete cases where
AI-generated output was overridden, corrected, or rejected. Format per `CLAUDE.md`:
every override entry has (1) what it ended up as, (2) the change as *this → that* with
the reasoning, (3) the code diff and its commit — commit filled in at the pre-push
check when it was pending at write time.

## Tools in use

**Claude Code (Anthropic CLI)** — in use since project start (2026-08-11) for design
interrogation, scaffolding, implementation, and maintenance of the living documents.
All design decisions are the user's; the records in `DESIGN_RECORDS.md` mark where a
decision was the user's call against an AI recommendation.

---

## Front-stage toggle structure: single gate switch → independent prompt-part toggles

**Timestamp:** 2026-08-12 07:34 -07:00

**1. What it ended up as:** the front-stage toggle config — `FrontStageConfig` with
independent `gate` and `rewrite` booleans, prompt sections and response schemas that
track the toggles, and a skip path when both are off.

**2. The change and the reasoning:** the AI proposed a single gate on/off request
parameter beside the rewrite toggle, with one combined prompt and the gate mandatory
for in-app traffic (per the then-recorded "the rewrite is optional, the gate is not"
design). The user redefined it: two independent toggles, each controlling its own part
of the prompt — gate part and rewrite part — so the eval harness can run both, either,
or neither, and with both off the LLM call is skipped entirely. Reasoning: each
behavior's before/after delta must be measurable in isolation; a combined prompt with a
coarse switch can't isolate either. This shaped the whole module: per-config prompt
assembly (`build_system_prompt`), per-config response schemas (`verdict_model_for`
returning `GateVerdict` / `RewriteVerdict` / `FullVerdict`), and `front_stage_skipped`.

**3. Diff and commit:** implemented from scratch in this form in
`backend/retrieval/tools/front_stage.py` (new file — no prior version existed; the
rejected shape was a design proposal, not code). Commit: `1938248` (the toggle
composition in its final two-tool form; the superseded single-call module was never
committed).

---

## Front-stage failure direction: typed API error → fail closed

**Timestamp:** 2026-08-12 07:34 -07:00

**1. What it ended up as:** the `except OpenAIError` branch of `run_front_stage`,
which returns `Refusal(text=FRONT_STAGE_UNAVAILABLE)` instead of raising.

**2. The change and the reasoning:** the AI recommended surfacing a front-stage call
failure as a typed API error (the UI's error state shows an outage as an outage,
consistent with the graded error-states deliverable and the no-retry rule). The user
chose fail-closed: a failed gate call refuses the query with a distinct canned
"can't process this right now" message rather than answering ungated or erroring.
Reasoning: the gate is a graded safety behavior and its failure direction should be
the safe one; the distinct message keeps outages distinguishable from medical-advice
refusals.

**3. Diff and commit:** the fail-closed branch in
`backend/retrieval/tools/front_stage.py` (new file, written directly in the chosen
form):

```python
    try:
        completion = client.chat.completions.parse(
            model=FRONT_STAGE_MODEL,
            messages=build_messages(query, history, config),
            response_format=verdict_model_for(config),
        )
    except OpenAIError:
        return Refusal(text=FRONT_STAGE_UNAVAILABLE)
```

Commit: `c92fc35` (the fail-closed branch lives in `advice_gate.py`'s
`run_advice_gate` after the two-tool split).

---

## Prompt/message layout: inline constants → per-file packages with index imports

**Timestamp:** 2026-08-12 08:40 -07:00

**1. What it ended up as:** the `backend/prompts/` and `backend/messages/` packages —
one constant per module (`front_stage_base.py`, `front_stage_gate.py`,
`front_stage_rewrite.py`; `personal_advice_refusal.py`, `front_stage_unavailable.py`),
each re-exported through its package `__init__.py` index.

**2. The change and the reasoning:** the AI wrote the three prompt pieces and two
canned responses as module-level constants inline in
`backend/retrieval/tools/front_stage.py`. The user directed the restructure: prompts
and automated messages in their own folders, one prompt per file, imported through a
package index (`from prompts import FRONT_STAGE_GATE`). Reasoning: prompts and
refusal texts are content artifacts read and edited on their own terms, and the
convention scales to the coming generation and reranker prompts without interleaving
text with pipeline code.

**3. Diff and commit:** the five constants moved verbatim out of `front_stage.py`
into the new modules; `front_stage.py` and `tests/test_front_stage.py` now import
them (`from messages import FRONT_STAGE_UNAVAILABLE, PERSONAL_ADVICE_REFUSAL` /
`from prompts import FRONT_STAGE_BASE, FRONT_STAGE_GATE, FRONT_STAGE_REWRITE`), and
`pyproject.toml`'s mypy `files` list gained `"messages"` and `"prompts"`. Constants
renamed with the move: `SYSTEM_PROMPT_BASE` → `FRONT_STAGE_BASE`, `GATE_SECTION` →
`FRONT_STAGE_GATE`, `REWRITE_SECTION` → `FRONT_STAGE_REWRITE` (package-level names
need the stage prefix). Commit: `bad810b` (the packages landed with
`advice_gate.py`/`query_rewrite.py` prompt files after the two-tool split renamed the
front_stage files).

---

## Combined front-stage module → two self-contained tools composed by the pipeline

**Timestamp:** 2026-08-12 08:56 -07:00

**1. What it ended up as:** `retrieval/tools/advice_gate.py` and
`retrieval/tools/query_rewriter.py` — each with its own prompt, schema, and LLM
call — composed by `prepare_query()` in `retrieval/pipeline.py`, with shared history
rendering in `retrieval/tools/history.py`.

**2. The change and the reasoning:** the AI built the gate and rewriter as one
`front_stage.py` module making a single combined LLM call, with toggles selecting
prompt sections and merged response schemas inside the module. The user rejected the
structure on two grounds: the name describes the stage's *position*, not what the code
does, and the module was doing the pipeline's job — tools must be separate from the
pipeline, and the pipeline is where it all comes together. The AI presented two
restructure plans (A: two tools with individual calls; B: logic-only tools sharing one
pipeline-assembled call); the user selected B, then reversed to A in the same exchange.
The split also bought per-tool failure semantics the combined call could not express:
gate fails closed, rewriter falls back to the raw query.

**3. Diff and commit:** `front_stage.py`, its tests, and the `front_stage_*` prompt/
message files were deleted; `advice_gate.py`, `query_rewriter.py`, `history.py`,
`prompts/advice_gate.py`, `prompts/query_rewrite.py`, `messages/gate_unavailable.py`,
and per-tool test files replaced them, and `pipeline.py` gained `prepare_query()`.
`FullVerdict`, `verdict_model_for`, and the section-assembly logic were deleted
outright — each tool now has a fixed prompt and a concrete schema (which also removed
the `cast` the merged-schema parse needed). Commits: `f07ca9f` (shared history),
`c92fc35` (advice gate), `a66d5ec` (query rewriter), `1938248` (pipeline
composition).

---

## Row-model and schema-check typing: `Any` annotations → precise types

**Timestamp:** 2026-08-12 09:29 -07:00

**1. What it ended up as:** the type annotations in `persistence/rows.py`
(`MessageRow.sources`), `persistence/migrate.py`, and `healthcheck.py` —
`dict[str, JsonValue] | None`, `psycopg.Connection[TupleRow]`, and `object`-typed
annotation introspection.

**2. The change and the reasoning:** the AI wrote three `Any`-based annotations:
`sources: dict[str, Any] | None` for the jsonb citation snapshot,
`psycopg.Connection[Any]` on connection parameters, and `annotation: Any` plus
`PG_TYPES: dict[Any, set[str]]` in the schema check's annotation→Postgres-type mapping.
The user rejected ambient `Any` ("we should stay away from ambiguous types like that
unless necessary"). Each had a strictly more precise replacement: pydantic's `JsonValue`
states "arbitrary JSON read whole" without erasing type checking; `TupleRow` names
psycopg's actual row contract for these connections instead of leaving the generic
open; `object` is the correct strict type for "a type-annotation object that must be
narrowed before use", which is exactly what `expected_column` does with it. After the
change, no `Any` remains in the backend's own signatures — the residual ambiguity
(`TupleRow = tuple[Any, ...]`, `get_args` returning `Any`) lives inside psycopg's and
typing's own contracts, not in project code.

**3. Diff and commit:** carried by commit `13bec39` on `database-schema` (PR #6) —
originally committed as `f1c2059` on `db-schema`, then squashed into the branch's
single commit before push.

```diff
--- a/backend/healthcheck.py
+++ b/backend/healthcheck.py
@@ -7,10 +7,11 @@
 from datetime import datetime
 from types import UnionType
-from typing import Any, Literal, Union, get_args, get_origin
+from typing import Literal, Union, get_args, get_origin
 from uuid import UUID

 import psycopg
+from psycopg.rows import TupleRow
 from pydantic import BaseModel
@@ -23,7 +24,7 @@
-PG_TYPES: dict[Any, set[str]] = {
+PG_TYPES: dict[object, set[str]] = {
     str: {"text"},
     int: {"integer", "bigint"},
     datetime: {"timestamp with time zone"},
@@ -31,7 +32,7 @@
-def expected_column(annotation: Any) -> tuple[set[str], bool]:
+def expected_column(annotation: object) -> tuple[set[str], bool]:
     """Map a model field annotation to (acceptable Postgres data types, nullable)."""
@@ -69,7 +70,7 @@
-def table_columns(conn: psycopg.Connection[Any], table: str) -> dict[str, tuple[str, bool]]:
+def table_columns(conn: psycopg.Connection[TupleRow], table: str) -> dict[str, tuple[str, bool]]:
     """Read a table's live columns as {name: (data_type, nullable)}."""
--- a/backend/persistence/migrate.py
+++ b/backend/persistence/migrate.py
@@ -4,9 +4,9 @@
 from pathlib import Path
-from typing import Any

 import psycopg
+from psycopg.rows import TupleRow
@@ -21,7 +21,7 @@
-def applied_migrations(conn: psycopg.Connection[Any]) -> set[str]:
+def applied_migrations(conn: psycopg.Connection[TupleRow]) -> set[str]:
@@ -32,7 +32,7 @@
-def apply_migration(conn: psycopg.Connection[Any], filename: str) -> None:
+def apply_migration(conn: psycopg.Connection[TupleRow], filename: str) -> None:
--- a/backend/persistence/rows.py
+++ b/backend/persistence/rows.py
@@ -6,10 +6,10 @@
 from datetime import datetime
-from typing import Any, Literal
+from typing import Literal
 from uuid import UUID

-from pydantic import BaseModel
+from pydantic import BaseModel, JsonValue
@@ -49,5 +49,5 @@
     content: str
     # Write-once tag→citation snapshot, read whole; its inner shape is owned by
     # the streaming contract and typed there once that exists.
-    sources: dict[str, Any] | None
+    sources: dict[str, JsonValue] | None
     created_at: datetime
```

---

## Embedding constants: tool-local constant → `.env` → project-wide constants in `config.py`

**Timestamp:** 2026-08-12 10:42 -07:00

**1. What it ended up as:** `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` in
`backend/config.py`, imported by `retrieval/tools/embedder.py` and (once it exists)
ingestion.

**2. The change and the reasoning:** the AI first proposed defining the model name and
dimension count inside `retrieval/tools/embedder.py`, on the project's own
"each tool is self-contained" convention. The user rejected the placement — a value both
ingestion and retrieval depend on should not be "hidden in some random file that you have
to search for" — and proposed `.env` so it would be project-wide. The AI argued against
`.env` specifically: the width is already frozen into the schema as `vector(1536)` and
every stored vector came from one specific model, so the value is not environment-tunable
— changing it would break the app rather than reconfigure it, and `.env` files differing
per machine would reintroduce exactly the drift a single definition prevents. The user's
actual requirement — one obvious project-wide place — is met by `config.py` constants,
which is the file a reader already opens for settings. Both the AI's original placement
and the user's first alternative were dropped; the resolution took the user's requirement
and the AI's objection together. Separately, the user chose the batched
`embed_texts(client, texts)` shape over a query-only embedder so ingestion imports this
function rather than defining the constants a second time.

**3. Diff and commit:** carried by commit `766856c` on `retrieval-toolbox` (PR #10).

```diff
--- a/backend/config.py
+++ b/backend/config.py
@@ -1,6 +1,14 @@
 from pydantic_settings import BaseSettings, SettingsConfigDict

+# Fixed, not environment-tunable: ingestion and retrieval must embed with the same
+# model at the same width or their vectors are not comparable, and the width is
+# already frozen into the schema as vector(1536) (see 0001_initial_schema.sql).
+# text-embedding-3-large is truncated from its native 3072 dims via the API's
+# `dimensions` parameter because pgvector's HNSW index caps at 2000.
+EMBEDDING_MODEL = "text-embedding-3-large"
+EMBEDDING_DIMENSIONS = 1536
+
--- a/backend/retrieval/tools/embedder.py
+++ b/backend/retrieval/tools/embedder.py
-EMBEDDING_MODEL = "text-embedding-3-large"      # AI's original: tool-local
-EMBEDDING_DIMENSIONS = 1536
+from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
```

---

## Connection annotations in the new retrieval tools: `Any` reintroduced → `TupleRow`

**Timestamp:** 2026-08-12 10:42 -07:00

**1. What it ended up as:** the `psycopg.Connection[TupleRow]` annotations in
`retrieval/tools/chunks.py`, `dense_search.py`, `sparse_search.py`, `retrieval/pipeline.py`,
and the precisely-typed fake in `tests/test_embedder.py`.

**2. The change and the reasoning:** writing the search tools, the AI annotated every
connection parameter `psycopg.Connection[Any]` and gave the embedder test's fake
`create(self, **kwargs: Any)` with a `dict[str, Any]` record — reintroducing exactly the
ambient `Any` the user rejected on 2026-08-12 09:29 ("we should stay away from ambiguous
types like that unless necessary", recorded above). Nothing caught it automatically:
mypy `strict` accepts `Any` silently, and lint has no opinion. It was found by re-reading
this records file before appending to it, which is the point of keeping the file.
Corrected to `TupleRow` — psycopg's real default row contract, and what
`healthcheck.py`/`migrate.py` already use — and the test fake was retyped with the actual
keyword parameters it stands in for, which additionally makes the fake assert the SDK
call shape instead of swallowing any arguments. No `Any` annotation remains in
`retrieval/` or `tests/`.

**3. Diff and commit:** the corrected form is what reached the history — `8ebba12`
(chunk_rows, dense, sparse), `73cb7e0` (pipeline), `2bdcab4` (the embedder test), all on
`retrieval-toolbox` (PR #10). The `Any` version never appears as a diff: it existed only
in the working tree, and the branch's commits were authored afterwards as a clean
sequence. Recorded here precisely because the history cannot show it.

```diff
--- a/backend/retrieval/tools/chunks.py      (also dense_search.py, sparse_search.py, pipeline.py)
+++ b/backend/retrieval/tools/chunks.py
-from typing import Any
-
 import psycopg
 from psycopg import sql
-from psycopg.rows import dict_row
+from psycopg.rows import TupleRow, dict_row

-def fetch_chunks(conn: psycopg.Connection[Any], ...) -> list[ChunkRow]:
+def fetch_chunks(conn: psycopg.Connection[TupleRow], ...) -> list[ChunkRow]:
--- a/backend/tests/test_embedder.py
+++ b/backend/tests/test_embedder.py
-        self.request: dict[str, Any] = {}
+        self.request: dict[str, object] = {}

-    def create(self, **kwargs: Any) -> _Response:
-        self.request = kwargs
-        positions = reversed(range(len(kwargs["input"])))
+    def create(self, *, model: str, input: list[str], dimensions: int) -> _Response:
+        self.request = {"model": model, "input": input, "dimensions": dimensions}
+        positions = reversed(range(len(input)))
```

---

## Reranker sampling: AI-drafted "temperature 0" → no temperature parameter

**Timestamp:** 2026-08-12 10:42 -07:00

**1. What it ended up as:** the `client.chat.completions.parse` call in
`retrieval/tools/reranker.py`, and the reranker paragraph in `DESIGN.md`.

**2. The change and the reasoning:** the reranker design — AI-drafted and previously
recorded — specified "one batched pointwise call scoring all ~20 candidates 0–10 as
structured JSON **at temperature 0**". The gpt-5 family accepts only its default
temperature, so implementing the design as written would have produced a call that fails
at request time rather than a deterministic reranker. The parameter is omitted and the
design text corrected. The reasoning behind "temperature 0" survives intact and is
better served by the existing structure: the model returns scores, the *sort* happens in
code, so run-to-run stability never depended on the sampler. This is a case where the
AI's own earlier design text was wrong about the provider's API and the code would have
been written to match it if it had not been checked.

**3. Diff and commit:** carried by commit `4701cb4` on `retrieval-toolbox` (PR #10). As
with the entry above, the `temperature=0` version never reached the history — the
reranker was first committed already corrected. `DESIGN.md` is untracked by design. `DESIGN.md` is untracked by design.

```diff
--- a/DESIGN.md
+++ b/DESIGN.md
-scoring all ~20 candidates 0–10 as structured JSON at temperature 0. The *sort* happens
-in code (tie-break falls back to RRF order; malformed/missing scores fall back to fused
-order), keeping the numeric scores for the eval trace.
+scoring all 20 candidates 0–10 as structured output. **No temperature is set** — the
+gpt-5 family only accepts its default; determinism comes from the sort living in code,
+not from the sampler.
--- a/backend/retrieval/tools/reranker.py
+++ b/backend/retrieval/tools/reranker.py
         completion = client.chat.completions.parse(
             model=RERANKER_MODEL,
             messages=build_rerank_messages(query, candidates),
-            temperature=0,
             response_format=RerankScores,
         )
```

---

## LangChain scope: "splitter only, raw SDK for LLM calls" → every LLM call through `ChatOpenAI`

**Timestamp:** 2026-08-12 11:12 -07:00

**1. What it ended up as:** the `langchain-openai` dependency, `chat/generation.py`'s
`ChatOpenAI` model factory and `astream` call, and the LangChain scope paragraph in
`DESIGN.md`'s stack section.

**2. The change and the reasoning:** asked what LangChain would actually offer at this
point in the build, the AI audited the remaining work and reported that the backend
imported LangChain in zero files, that `langchain` 1.3.15 is an agent framework pulling
langgraph and langsmith into the deliberately lean container, that `langchain-openai` and
`langchain-text-splitters` were both absent from the lock file, and that exactly one
component — the recursive text splitter — had a genuine case. On that basis the AI
recommended using the splitter in ingestion and calling the OpenAI SDK directly for all
four LLM call sites, arguing that `ChatOpenAI`'s benefits here (provider swappability,
retry/callback hooks) are ones this project has already declined. The user rejected that
and set the opposite rule: every LLM call goes through `ChatOpenAI`, with the gate and
rewriter retrofitted separately. Reasoning: uniformity across call sites is worth more
than shaving one abstraction, because "why LangChain here and not there?" is a harder
question to defend in the follow-up interview than "why LangChain at all?" — the latter
has a one-paragraph answer, which now sits in `DESIGN.md`. Note the AI's own earlier
recommendation had been *for* uniformity and it reversed to splitter-only after the audit;
the user's decision restored the original direction on the stronger reasoning.

**3. Diff and commit:** `langchain-openai` added to `backend/pyproject.toml`; generation
built directly in this form (no prior version existed):

```python
def generation_model(api_key: str) -> ChatOpenAI:
    return ChatOpenAI(model=GENERATION_MODEL, api_key=SecretStr(api_key))


async def stream_answer(model: BaseChatModel, question: str, context: str) -> AsyncIterator[str]:
    async for chunk in model.astream(build_answer_messages(question, context)):
        if chunk.text:
            yield chunk.text
```

Commits: `5e02e26` (the dependency), `614329e` (the generation call).

---

## Chunk input seam: recommended projection model → `Protocol`, and a corrected leak claim

**Timestamp:** 2026-08-12 11:12 -07:00

**1. What it ended up as:** the `CitedDocument` `Protocol` and the `RetrievedChunk` frozen
dataclass in `backend/chat/context.py`.

**2. The change and the reasoning:** the AI first offered only two shapes — the
`ChunkRow` + `DocumentRow` pair, or a flat model re-declaring the seven fields `chat/`
uses — and recommended the pair. The user asked whether the rows could be referenced while
the unneeded document fields were gated out, which the AI had not offered; it then surfaced
two mechanisms (a narrow base class in `rows.py`, or a `Protocol` in `chat/`). The user
then asked for `DocumentRow` to be the base with a `CitedDocument` excluding fields from
it. The AI reported that this specific arrangement is not expressible — inheritance adds
members and cannot remove them, and substitutability forces the narrower type to be the
base — and recommended instead a projection model with a `.of(DocumentRow)` constructor
plus a hermetic drift test. The user rejected that too and chose the `Protocol`, which
enforces the gate at type-check time rather than at runtime plus CI.

Separately, a claim the AI made in arguing for input gating was corrected in the same
exchange: it described the full pair as putting document internals "in reach of
prompt-assembly code," implying a leak risk. That was wrong — what escapes is bounded by
the `Citation` model on the way out and by explicit field reads, so input gating buys
tidiness and blast radius, not leak prevention. The correction is recorded in
`DESIGN_RECORDS.md` rather than left standing as the justification.

**3. Diff and commit:** written directly in the chosen form in
`backend/chat/context.py` (new file):

```python
class CitedDocument(Protocol):
    id: str
    drug_name: str


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: ChunkRow
    document: CitedDocument
```

Verified with a throwaway module that `retrieved.document.ingested_at` inside `chat/`
raises mypy `"CitedDocument" has no attribute "ingested_at"` while a `DocumentRow` passes
in cleanly. Commit: `c1276d4`.

---

## Citation payload: recommended manufacturer + formulation → neither

**Timestamp:** 2026-08-12 11:12 -07:00

**1. What it ended up as:** the `Citation` model in `backend/chat/context.py` — five
fields, no labeler or formulation.

**2. The change and the reasoning:** while defining the sources payload the AI found that
13 of the 17 corpus documents belong to a drug with more than one label, so citations
rendering as drug + section are ambiguous between up to three documents, and it
recommended adding `manufacturer` and `formulation` to disambiguate — arguing the
look-alike discrimination the hybrid stretch goal performs would otherwise be visible only
in the eval trace and never in the UI. The user rejected the addition and kept the payload
exactly as `DESIGN.md` specifies. Reasoning implied by the choice: `document_id` is already
in the payload and resolves click-through to the right PDF and page, so nothing is
functionally broken, and the smaller payload is also what gets frozen into every
`messages.sources` snapshot. The finding itself was kept — the accepted ambiguity is
written down in `DESIGN_RECORDS.md` rather than dropped, so it can be revisited once the
UI is real.

**3. Diff and commit:** written in the chosen form in `backend/chat/context.py`:

```python
class Citation(BaseModel):
    document_id: str
    drug: str
    section_number: str | None
    section_title: str | None
    page_start: int
```

Commit: `c1276d4`.

---

## Reranker client: raw OpenAI SDK → `ChatOpenAI.with_structured_output`

**Timestamp:** 2026-08-12 11:41 -07:00

**1. What it ended up as:** `build_reranker()` and `run_reranker()` in
`retrieval/tools/reranker.py`, and `build_embeddings()` in `retrieval/tools/embedder.py`.

**2. The change and the reasoning:** the AI wrote both tools against the raw OpenAI SDK —
`client.chat.completions.parse(response_format=RerankScores)` and
`client.embeddings.create(model=..., dimensions=...)` — matching the two already-merged
tools beside them. That was wrong against the current design: `DESIGN.md`'s one-rule
LangChain scope names the reranker as a `ChatOpenAI` call. The AI surfaced the conflict
rather than either silently following the older sibling code or silently rewriting two
merged tools, and offered three ways out. The user chose to move the reranker now
(net-new code should meet the current rule, and the pending migration shrinks rather than
grows) and additionally extended the rule to embeddings, which the AI had recommended
leaving on the raw SDK — the AI's reasoning was that `OpenAIEmbeddings` wraps a call with
no chain, prompt, or streaming to benefit from; the user's is that one client library for
every OpenAI call leaves no exception to remember. The user's rule won.

A second AI recommendation was dropped in the process: `embed_texts()` / `embed_query()`
wrappers, including hand-written re-sorting of the batch by each item's `index`. Against
`OpenAIEmbeddings` those became pure passthroughs to `embed_documents` / `embed_query`,
and the ordering guarantee is the library's, so the wrappers were deleted rather than
kept — the embedder tool is now the factory alone.

**3. Diff and commit:** carried by commits `4701cb4` (reranker), `2bdcab4` (embedder),
on `retrieval-toolbox` (PR #10). The `langchain-openai` dependency is **not** carried by
this branch: the parallel chat session added the identical line in PR #9 (`5e02e26`)
while this work was in flight, and the duplicate addition collapsed to nothing when
this branch was rebased onto it.

```diff
--- a/backend/retrieval/tools/reranker.py
+++ b/backend/retrieval/tools/reranker.py
-from openai import OpenAI, OpenAIError
+from langchain_core.language_models import LanguageModelInput
+from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
+from langchain_core.runnables import Runnable
+from langchain_openai import ChatOpenAI
+from openai import OpenAIError

+RerankerModel = Runnable[LanguageModelInput, object]
+
+def build_reranker() -> RerankerModel:
+    return ChatOpenAI(model=RERANKER_MODEL).with_structured_output(RerankScores)

-def run_reranker(client: OpenAI, query, candidates):
+def run_reranker(model: RerankerModel, query, candidates):
     try:
-        completion = client.chat.completions.parse(
-            model=RERANKER_MODEL,
-            messages=build_rerank_messages(query, candidates),
-            response_format=RerankScores,
-        )
+        parsed = model.invoke(build_rerank_messages(query, candidates))
     except OpenAIError:
         return candidates
-    return apply_scores(candidates, completion.choices[0].message.parsed)
+    return apply_scores(candidates, parsed if isinstance(parsed, RerankScores) else None)
--- a/backend/retrieval/tools/embedder.py
+++ b/backend/retrieval/tools/embedder.py
-def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
-    response = client.embeddings.create(
-        model=EMBEDDING_MODEL, input=texts, dimensions=EMBEDDING_DIMENSIONS
-    )
-    return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
-
-def embed_query(client: OpenAI, query: str) -> list[float]:
-    return embed_texts(client, [query])[0]
+def build_embeddings() -> OpenAIEmbeddings:
+    return OpenAIEmbeddings(model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS)
--- a/backend/pyproject.toml
+++ b/backend/pyproject.toml
     "langchain",
+    "langchain-openai",
     "openai",
```

---

## Ingestion location: a backend package with a dependency group → a standalone project

**Timestamp:** 2026-08-12 11:32 -07:00

**1. What it ended up as:** the top-level `ingestion/` project — its own
`pyproject.toml`, `uv.lock`, `Dockerfile`, and `tests/`, beside `backend/` and
`frontend/`.

**2. The change and the reasoning:** the AI proposed keeping ingestion at
`backend/ingestion/` and isolating `unstructured[pdf]` in a non-default dependency
group, on the grounds that one toolchain is simpler and the backend image just skips the
group. The user rejected the premise: ingestion is never called through the API, so it
does not belong inside the API project, and if it ever needs exposing it becomes its own
service. Reasoning the user gave: "We don't need ingestion on the backend since we never
call it through API." The AI agreed on review and added a second argument the user had
not raised — a separate lockfile makes the lean-backend property structural rather than
procedural, since the backend image then *cannot* resolve `unstructured` at all. The AI
did push back on one part and the user accepted it: the schema keeps a single owner in
`backend/persistence/migrations/` rather than being duplicated or split.

**3. Diff and commit:** deletion of `backend/Dockerfile.ingestion` and
`backend/ingestion/{__init__,__main__}.py`, removal of `"ingestion"` from the backend
mypy `files` list, and the new `ingestion/` tree.

```diff
--- a/backend/pyproject.toml
+++ b/backend/pyproject.toml
-files = ["api", "chat", "config.py", "healthcheck.py", "ingestion", "messages", "persistence", "prompts", "retrieval", "tests"]
+files = ["api", "chat", "config.py", "healthcheck.py", "messages", "persistence", "prompts", "retrieval", "tests"]
```

Commit: pending.

---

## Document identity: a hand-authored manifest → one LLM extraction call per document

**Timestamp:** 2026-08-12 11:32 -07:00

**1. What it ended up as:** `ingestion/identity.py` — a single `gpt-5-mini`
structured-output call per new or changed document returning `drug_name`,
`manufacturer`, and `formulation`, raising `IngestionError` on failure.

**2. The change and the reasoning:** `documents.drug_name` and `manufacturer` are
`NOT NULL`, and nothing in the design said where ingestion gets them. The AI recommended
a hand-authored manifest checked into the repo and keyed by object key — deterministic,
free, hermetically testable, and loud about unknown documents. The user chose LLM
extraction instead. The manifest would have made the bucket only half the source of
truth: the design has ingestion reconcile against the bucket, and a checked-in list of
what the bucket contains is a second, drift-prone copy of that fact. The AI kept the
failure direction it had argued for — extraction failure aborts the document rather than
falling back to the filename, matching the way unresolvable pages already fail.

**3. Diff and commit:** `ingestion/identity.py` and
`ingestion/prompts/document_identity.py`, both new files; the rejected shape was a
design proposal and never written.

Commit: pending.

---

## Heading detection: a word-count floor → a character floor plus a section-number bound

**Timestamp:** 2026-08-12 11:32 -07:00

**1. What it ended up as:** the guard conditions in `carving.numbered_heading` —
`MIN_HEADING_TITLE_CHARS = 3` and `MAX_SECTION_NUMBER = 17`.

**2. The change and the reasoning:** the AI wrote `if len(title.split()) < 2: return
None` to stop carton lines such as `1 mg:` from being read as section headings, and the
rule looked reasonable in isolation. Run against the corpus it rejected
`5.1 Hemorrhage`, `11 DESCRIPTION`, and `5.4 Proarrhythmia`: single-word section titles
are ordinary in a PLR label. The measurable damage was 12–16 detected top-level sections
per document against a true 15–16, and roughly a quarter of all subsections silently
dropped — which would have shipped as missing citations, not as an error. Replaced by a
3-character floor plus a bound of 1–17 on the section number, since PLR defines exactly
those sections; the carton lines it was written to reject (`1 mg:`, `10 mg White (dye`,
`30 Tablets`) are all still rejected, by the terminator rule, the uppercase-remainder
rule, and the bound respectively.

**3. Diff and commit:**

```diff
--- a/ingestion/carving.py
+++ b/ingestion/carving.py
-MIN_HEADING_WORDS = 2
+MIN_HEADING_TITLE_CHARS = 3
+MAX_SECTION_NUMBER = 17
@@
-    if len(title.split()) < MIN_HEADING_WORDS:
+    if len(title) < MIN_HEADING_TITLE_CHARS:
         return None
     major, minor, _ = match.groups()
+    if not 1 <= int(major) <= MAX_SECTION_NUMBER:
+        return None
```

Commit: pending.

---

## Section ordering: a monotonic-numbering guard, proposed and rejected before shipping

**Timestamp:** 2026-08-12 11:32 -07:00

**1. What it ended up as:** nothing — no ordering guard exists in `carving.py`.

**2. The change and the reasoning:** the AI proposed accepting a top-level heading only
when its number exceeded the last accepted one, arguing that PLR sections run 1→17 in
regulatory order so monotonicity is a free correctness check against stray matches.
Measured against the corpus, 6 of 17 documents are non-monotonic in extraction order, so
the guard would have rejected real headings and dropped real sections. Rejected before
any of it was written into the module. The false positives it was meant to catch are
handled by the number bound instead, which is checked per heading and needs no state.

**3. Diff and commit:** no diff — the rule was measured and abandoned at the probe stage.
The evidence is recorded in `DESIGN_RECORDS.md` under "Carving boundaries".

Commit: n/a.

---

## Table page spans: inferred from the next element → carried on the element

**Timestamp:** 2026-08-12 11:32 -07:00

**1. What it ended up as:** `PageElement.page_start` / `PageElement.page_end`, set equal
by extraction and widened by `cleaning.stitch_cross_page_tables`.

**2. The change and the reasoning:** the AI's first version gave `PageElement` a single
`page` and recovered a stitched table's end page with a helper that looked ahead for the
next element on a later page. That is a guess, and it is wrong exactly when a table is
the last block on its page — which is the common case for a table long enough to have
been split across pages in the first place. Since page is the schema's `NOT NULL`
citation floor, an inferred value is the wrong shape of answer: the element now carries
the span it actually covers, and the lookahead helper was deleted rather than fixed.

**3. Diff and commit:**

```diff
--- a/ingestion/cleaning.py
+++ b/ingestion/cleaning.py
-def table_page_span(elements: Sequence[PageElement], index: int) -> int:
-    """Last page a stitched table covers, read back from the elements that follow it."""
-    table = elements[index]
-    following = next((e for e in elements[index + 1 :] if e.page > table.page), None)
-    return table.page if following is None else following.page - 1
```

Commit: pending.

---

## Retrieval file structure: flat `tools/` bag → stage packages

**Timestamp:** 2026-08-12 12:06 -07:00

**1. What it ended up as:** the `retrieval/` package layout — `contract.py` plus the
`query/`, `search/`, and `ranking/` stage packages, with `tests/retrieval/` mirroring it.

**2. The change and the reasoning:** the AI built the retrieval toolbox as nine flat
modules in `retrieval/tools/`, following the project's recorded "each tool self-contained
in `retrieval/tools/`" convention literally. It applied that convention to things that
were not tools: `chunks.py` accumulated a SQL fragment, a row reader, and the
`ScoredChunk` domain type, and `history.py` mixed a boundary-crossing type with a
prompt helper. The AI wrote both files that way without flagging the mismatch, and
`Refusal` was left defined inside the advice-gate tool while being half of the pipeline's
public return type.

The user rejected the structure on inspection — "the tools and file structure of retrieval
could use some cleaning up" — and asked for a plan rather than an immediate change. Given
three options, the user chose the deepest one: retire `tools/` entirely in favour of
folders named for the pipeline stages, accepting that this supersedes their own earlier
`tools/` naming convention. The AI's own recommendation had been the same shape, but the
AI had not raised the problem on its own in the two sessions it spent writing those files.

**3. Diff and commit:** carried by commit `6e6fd89` on `retrieval-toolbox` (PR #10) — the
first commit on the branch, deliberately pure motion so the restructure reads as a
rename-only diff. The flat `tools/` layout it replaced exists on `main`, not in this
branch's history. Motion only — no behavior changed, all 33 tests pass before and
after.

```diff
 retrieval/
-  tools/
-    advice_gate.py  chunks.py      dense_search.py  embedder.py  fusion.py
-    history.py      query_rewriter.py  reranker.py  sparse_search.py
+  contract.py        HistoryMessage, ScoredChunk, Refusal, Retrieved
+  query/
+    advice_gate.py  query_rewriter.py  transcript.py
+  search/
+    embedder.py     dense.py  sparse.py  chunk_rows.py
+  ranking/
+    fusion.py       reranker.py
--- a/backend/retrieval/pipeline.py
+++ b/backend/retrieval/pipeline.py
-from retrieval.tools.advice_gate import Refusal, run_advice_gate
-from retrieval.tools.chunks import ScoredChunk
-from retrieval.tools.dense_search import run_dense_search
-from retrieval.tools.fusion import fuse_rankings
-from retrieval.tools.history import HistoryMessage
-from retrieval.tools.query_rewriter import run_query_rewriter
-from retrieval.tools.reranker import RerankerModel, run_reranker
-from retrieval.tools.sparse_search import run_sparse_search
+from retrieval.contract import HistoryMessage, Refusal, Retrieved, ScoredChunk
+from retrieval.query.advice_gate import run_advice_gate
+from retrieval.query.query_rewriter import run_query_rewriter
+from retrieval.ranking.fusion import fuse_rankings
+from retrieval.ranking.reranker import RerankerModel, run_reranker
+from retrieval.search.dense import run_dense_search
+from retrieval.search.sparse import run_sparse_search
```

---

## Ingestion's OpenAI adapters: raw SDK → `langchain-openai`

**Timestamp:** 2026-08-12 12:01 -07:00

**1. What it ended up as:** `ingestion/identity.py` built on
`ChatOpenAI.with_structured_output(DocumentIdentity)` and `ingestion/embedding.py` built
on `OpenAIEmbeddings`, both injected into `ingest_document` as
`BaseChatModel` / `Embeddings`.

**2. The change and the reasoning:** the AI wrote both adapters on the raw OpenAI SDK —
`client.chat.completions.parse` and `client.embeddings.create` with a hand-rolled 64-item
batching loop — mirroring the advice gate and query rewriter, which were the only
examples in the repo at the time. Between that and this check, PR #9 merged the one-rule
LangChain scope, which names `ChatOpenAI` for every LLM call and `OpenAIEmbeddings` for
"both ingestion and query embedding". The user asked for the branch to be checked against
the new `main`; the adapters were the divergence. Rewritten to the rule rather than left
for a later sweep, because the code had not shipped and leaving it would have widened a
migration debt that already covers two merged tools. The batching loop was deleted rather
than ported — the client does it — but its length check was kept, since embeddings are
zipped with chunks at insert time and a short response would mispair rather than fail.

**3. Diff and commit:**

```diff
--- a/ingestion/embedding.py
+++ b/ingestion/embedding.py
-from openai import OpenAI
-EMBEDDING_BATCH = 64
-def embed_texts(client: OpenAI, texts: Sequence[str]) -> list[list[float]]:
-    vectors: list[list[float]] = []
-    for start in range(0, len(texts), EMBEDDING_BATCH):
-        batch = list(texts[start : start + EMBEDDING_BATCH])
-        response = client.embeddings.create(
-            model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS, input=batch
-        )
-        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
+from langchain_core.embeddings import Embeddings
+from langchain_openai import OpenAIEmbeddings
+def embed_texts(embeddings: Embeddings, texts: Sequence[str]) -> list[list[float]]:
+    if not texts:
+        return []
+    vectors = embeddings.embed_documents(list(texts))
     if len(vectors) != len(texts):
         raise IngestionError(f"Embedded {len(vectors)} of {len(texts)} chunks.")
     return vectors

--- a/ingestion/identity.py
+++ b/ingestion/identity.py
-    try:
-        completion = client.chat.completions.parse(
-            model=IDENTITY_MODEL, messages=..., response_format=DocumentIdentity
-        )
-    except OpenAIError as error:
-        raise IngestionError(...) from error
-    identity = completion.choices[0].message.parsed
-    if identity is None or not identity.drug_name.strip() or ...:
+    structured = model.with_structured_output(DocumentIdentity)
+    try:
+        parsed = structured.invoke(build_identity_messages(elements))
+    except OpenAIError as error:
+        raise IngestionError(...) from error
+    if not isinstance(parsed, DocumentIdentity):
+        raise IngestionError(...)
```

Commit: pending.

---

## Pre-push reconciliation for PR #10

**Timestamp:** 2026-08-12 12:31 -07:00

Not an override — a note on how to read the five entries above against the branch history.

The `retrieval-toolbox` branch was committed as an authored sequence of eight commits
*after* the work was finished, ordered by concern rather than by the order things actually
happened: restructure → dependency → config → embedder → search legs → fusion → reranker
→ composition. Each commit was verified green (ruff, strict mypy, pytest) with the working
tree at that commit's state, not merely at the tip.

The consequence for these records: several corrections logged above are **invisible in the
history**, because the corrected form is what was committed. The `Any` annotations, the
`temperature=0` reranker call, the raw-SDK clients, and the flat `tools/` folder all
existed in the working tree and none of them reached a commit. That is the intended
division — `DESIGN_RECORDS.md` and this file carry what the diff cannot.

Commit map for the branch:

| Commit | Concern |
|---|---|
| `6e6fd89` | Restructure retrieval into pipeline stages with a shared contract |
| `766856c` | Pin the embedding model and width as shared constants |
| `b98e282` | Retrieval configuration: one object for every switch and cut-off |
| `2bdcab4` | Embedder: the one configured embeddings client |
| `8ebba12` | Chunk search: dense vector and sparse full-text legs |
| `2bd941e` | Rank fusion: RRF across the two candidate legs |
| `4701cb4` | LLM reranker: batched pointwise scoring, sorted in code |
| `73cb7e0` | Compose the full retrieve path behind the config toggles |

---

## PR #10 rebased onto main; recorded commits remapped

**Timestamp:** 2026-08-12 12:19 -07:00

The SHAs recorded in the entries above were rewritten once, and the note explaining the
commit map now describes the post-rebase history. What happened:

PR #9 (the chat layer) merged to `main` while this branch was being committed, and it had
independently added `langchain-openai` to `backend/pyproject.toml` — the same one-line
change this branch made for the reranker and embeddings clients. `retrieval-toolbox` was
**rebased** onto the new `main` rather than merged, to keep the eight-commit sequence
linear and matching how every previous feature branch in this repo reads.

Three consequences, all recorded rather than quietly absorbed:

1. **Every SHA above changed.** The originals (`2f82cc6` … `06db6e3`) exist in no remote
   branch; the mapping in the reconciliation note is the post-rebase one.
2. **One commit's message became false and was rewritten.** "Pin the embedding model and
   width as shared constants" originally also added the `langchain-openai` dependency.
   After the rebase that hunk collapsed to nothing, so the commit changes only
   `config.py`, and the paragraph claiming the dependency was removed from its message.
   The message now describes exactly what the commit does.
3. **The only real conflict was `prompts/__init__.py`** — the chat session added
   `GROUNDED_ANSWER` and this branch added `RERANK` to the same `__all__`. Resolved by
   keeping both. `chat/` turned out not to import `retrieval` at all (it defines its own
   `RetrievedChunk` Protocol), so the package restructure did not touch it.

**Verified after the rebase:** each of the eight commits was checked out in turn and
passes ruff, strict mypy, and pytest on its own — not merely at the tip. CI on PR #10
passes both the backend and frontend jobs.

---

## Eval harness architecture: HTTP trace-mode driver → in-process package

**Timestamp:** 2026-08-12 13:00 -07:00

**1. What it ended up as:** the eval harness's architecture and location —
`backend/eval/`, run in-process via `python -m eval`.

**2. The change and the reasoning:** the AI's plan (Build-Spec §10, and the first
harness plan presented this session) had the harness as an external script under
`scripts/verification/` driving the deployed query endpoint's `?trace=true` mode over
HTTP. The user rejected the premise — the harness should not rely on the backend being
up to run. Redesigned to in-process: the harness imports the retrieval/chat core
directly (`run_retrieval()`, the chunk→document join, `trace_answer()`), opens its own
psycopg connection and model clients, and needs no server, no HTTP client, and no
endpoint to exist. It stays typed end to end instead of parsing JSON back into restated
shapes, and the query endpoint comes off the harness's critical path entirely. Location
moved into the backend so the imports are native (`healthcheck.py` precedent:
backend-resident, locally run, excluded from the deployed image).

**3. Diff and commit:** the new `backend/eval/` package (contracts + scoring + tests,
written directly in the in-process form — the rejected HTTP shape was design, not code,
so no prior version exists to diff against) and DESIGN.md's eval-harness section
rewrite. Commit: pending.

---

## Eval suite: AI-drafted, verified against extracted label text, pending owner review

**Timestamp:** 2026-08-12 13:58 -07:00

**Tool use, disclosed:** the 18 question/expected-answer pairs in `backend/eval/suite.py`
were drafted by Claude Code at the owner's direction ("draft all 18 and justify them"),
not hand-written first. The assignment requires a test set "you author yourself," so this
is recorded explicitly: every case's expected documents, section numbers, and expected
answer were verified during drafting against pypdf extractions of the actual corpus PDFs
(quotes retained in the session record), and the owner reviews, edits, and takes
ownership of the set before it is used for a graded run. Verification also surfaced
corpus facts recorded in `DESIGN_RECORDS.md` (Warfarin_2 numbering misalignments, the
amiodarone label being the IV formulation, the absence proofs behind the three
unanswerables). Commit: pending.

## Three corrections to the AI-built frontend data layer (PR #11)

**Timestamp:** 2026-08-12 13:19 -07:00

A review of the merged frontend data layer (PR #11, itself AI-generated in a parallel
session) against the backend SSE contract found three defects. All three were fixed on
`worktree-frontend-stream-fixes` and shipped as PR #15.

### 1. Sentinel-withholding regex

**What it ended up as:** the `TRAILING_PARTIAL_TAG` pattern in `frontend/src/lib/sentinels.ts`.

**The change and the reasoning:** `/\[\[?S?\d*$/` -> `/\[\[?S?\d*\]?$/`. The AI-written
pattern withheld `[[`, `[[S`, `[[S1` at a streaming boundary but not `[[S1]` — a token
split between the two closing brackets flashed the literal sentinel on screen for one
frame, violating the module's own stated contract ("it never flashes on screen as
literal text"). The optional trailing bracket closes the hole; a `'[[S1]'` case was
added to the existing withholding test.

**Diff (commit `336ffb0`):**
```diff
-const TRAILING_PARTIAL_TAG = /\[\[?S?\d*$/
+const TRAILING_PARTIAL_TAG = /\[\[?S?\d*\]?$/
```

### 2. Auto-scroll during streaming

**What it ended up as:** a bottom-anchor `useEffect` in `frontend/src/components/MessageList.tsx`.

**The change and the reasoning:** the AI-built message list had no scroll anchoring, so
once an answer grew past the fold, tokens streamed in below the visible area and the
user had to chase them. An empty `<li ref={endRef}>` plus
`endRef.current?.scrollIntoView?.()` keyed on message count and answer text keeps the
newest text in view. The second optional call is deliberate: jsdom implements no
`scrollIntoView`, and the first run without the guard crashed two existing ChatArea
tests.

**Diff (commit `ca41b5a`):** adds the ref/effect and the anchor `<li>`; no lines removed.

### 3. Partial-answer preservation

**What it ended up as:** a stalled-answer commit step in `ask()` in
`frontend/src/state/ConversationStore.tsx`.

**The change and the reasoning:** a failed stream kept its partial text labeled
"incomplete" in `answers[conversationId]` — but the next `ask` in that conversation
dispatched `answer/started`, overwriting it before it ever reached the transcript. The
one honest copy of the partial answer silently vanished, undercutting the store's own
comment that hiding partial text "is less honest than showing it". `ask()` now commits
a non-empty incomplete answer as an assistant message (text + sources snapshot) before
starting the next stream, reusing the existing `answer/completed` action.

**Diff (commit `f35065f`):**
```diff
+    // A partial answer left by a failed stream would be overwritten by the next
+    // `answer/started`; keep what arrived by committing it to the transcript first.
+    const stalled = state.answers[conversationId]
+    if (stalled !== undefined && stalled.status === 'incomplete' && stalled.text !== '') {
+      dispatch({
+        type: 'answer/completed',
+        conversationId,
+        message: localMessage(conversationId, 'assistant', stalled.text, stalled.sources),
+      })
+    }
```

Left unfixed on purpose (judged minor for a demo): a fast double-Enter during
conversation creation can create two conversations; asking in a conversation whose
detail fetch failed streams invisibly; `select()` reads its cache check from a stale
closure and can double-fetch.

---

## Frontend type safety: recommended Zod schemas → cast at the boundary

**Timestamp:** 2026-08-12 11:42 -07:00

**1. What it ended up as:** `frontend/src/api/http.ts`'s `request<T>()` — one `as T` cast
per response, and no runtime validation anywhere in the frontend.

**2. The change and the reasoning:** asked to make the data layer "securely typed", the AI
pointed out that the committed `types.ts` could not deliver that on its own, because
TypeScript types are erased at compile time and cannot check data that arrives at runtime.
It recommended Zod: one schema per payload, TS types inferred from it so there is a single
declaration rather than two that drift, `safeParse` at every boundary, and a typed error
routed into the UI's existing error state — explicitly modeled on the backend's own
`persistence/rows.py` discipline, where the docstring states the point is that "schema
drift surfaces as a typed validation error at the boundary". The argument was situational:
the backend contract was still moving, this branch is written against an `events.py` that
is not yet merged, and cutover day is when a validator pays for itself. The user asked what
Zod was, received the explanation, and then rejected it in favor of the smallest thing that
compiles. Reasoning implied by the choice, and consistent with `CLAUDE.md`: this is a demo
whose purpose is a reader following the code end to end, coverage is explicitly not graded,
and a validation layer that never fires before submission is weight with no reader-visible
payoff. The AI recorded the resulting asymmetry — backend validates, frontend asserts — as
debt in `DESIGN.md` rather than dropping the objection silently.

**3. Diff and commit:** commit `6c32243`.

```diff
+++ b/frontend/src/api/http.ts
+export async function request<T>(path: string, init?: RequestInit): Promise<T> {
+  const response = await fetch(apiUrl(path), init)
+  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
+  return (await response.json()) as T
+}
```

---

## Frontend mock: recommended MSW for dev and tests → stubbed `fetch` in tests only

**Timestamp:** 2026-08-12 11:42 -07:00

**1. What it ended up as:** `frontend/src/test/sse.ts` plus per-test `vi.stubGlobal('fetch', …)`.
No mock exists outside Vitest.

**2. The change and the reasoning:** the AI recommended Mock Service Worker, on the grounds
that one set of handlers would serve both Vitest and the dev browser, letting the graded
streaming and loading/error states be seen in a browser before the backend existed while
still exercising the real `fetch` and SSE parser. The user rejected the dependency and
scoped the mock to tests, having already clarified that the goal was proof the client
consumes the contract correctly, not a demo backend with believable data. The AI's own
third option — a Vite dev-server middleware — was argued against by the AI itself and also
not taken, because it produces two mock implementations of one contract that drift. What
survived from the recommendation is the part that mattered: the stub returns a real
`Response` around a real `ReadableStream`, so the production fetch call and frame parser
run unmodified, and tests deliberately split frames mid-frame across chunks.

**3. Diff and commit:** commits `29cad58` (tooling) and `6c32243` (fixtures and tests).

```diff
+++ b/frontend/vite.config.ts
+  test: {
+    environment: 'jsdom',
+    setupFiles: './src/test/setup.ts',
+    env: { VITE_API_BASE_URL: 'http://api.test' },
+  },
```

---

## `sources` event payload: the AI stated the wrong shape, then corrected it from the source

**Timestamp:** 2026-08-12 11:42 -07:00

**1. What it ended up as:** `toEvent()` in `frontend/src/api/stream.ts`, which reads
`payload.sources` rather than treating the frame payload as the mapping itself.

**2. The change and the reasoning:** while agreeing the SSE frame format with the user, the
AI illustrated the `sources` event as `data: {"S1": {...}}` — the tag→citation map sent
bare. That was wrong. `SourcesEvent` in `backend/chat/events.py` is a Pydantic model with a
`sources` field, so `model_dump_json()` wraps the map: `{"sources": {"S1": {...}}}`. The
error was caught by locating the real `events.py` — uncommitted, in a sibling worktree —
and reading it instead of continuing from the design prose, which describes event *order*
but never shows a payload. Had the AI's illustration been implemented, every citation in
every answer would have failed to resolve, and the frontend tests would have passed,
because the same wrong shape would have been written into the fixtures. The general lesson
is recorded because it generalizes: mocks written from an assumed contract validate the
assumption, not the contract.

**3. Diff and commit:** commit `6c32243`. The corrected read, against `events.py`:

```ts
case 'sources':
  return { name: 'sources', sources: payload.sources as SourcesMap }
```

---

## Committed frontend contract types: three drifts from the backend, corrected

**Timestamp:** 2026-08-12 11:42 -07:00

**1. What it ended up as:** the rewritten `frontend/src/api/types.ts`.

**2. The change and the reasoning:** the `types.ts` on `main`, written in the earlier
frontend-scaffolding session, had drifted from the design in three ways, all found by
reading the backend rather than the prose:

- `QueryRequest.mode: 'hybrid' | 'dense' | 'sparse'` — a field the design has since
  deleted. `DESIGN.md` now states "there is deliberately no retrieval *mode*", and
  `retrieval/pipeline.py` confirms the switches are independent booleans. Replaced with
  `gate` / `rewrite` / `sparse` / `rerank`.
- `QueryRequest.gating_variant?: string` — never existed in any backend signature.
  Removed.
- `Citation.page_start: number | null` — contradicted `DESIGN.md`'s stated citation floor
  ("page fields are not [nullable]"), the `page_start int NOT NULL` column, and
  `Citation.page_start: int` in `chat/context.py`. Tightened to `number`. Left as-is it
  would have forced dead null-handling into every citation render and made the guaranteed
  floor look optional.

None of these were user-directed changes; they are corrections of earlier AI output that
had been merged. They are recorded because the cast-not-validate decision means type drift
has no runtime backstop, so reading the backend source is now the only mechanism keeping
the two sides aligned.

**3. Diff and commit:** commit `6c32243`.

```diff
--- a/frontend/src/api/types.ts
+++ b/frontend/src/api/types.ts
-  page_start: number | null
+  page_start: number

-export type RetrievalMode = 'hybrid' | 'dense' | 'sparse'
 export interface QueryRequest {
   question: string
-  mode?: RetrievalMode
+  gate?: boolean
   rewrite?: boolean
+  sparse?: boolean
   rerank?: boolean
-  gating_variant?: string
   judge?: boolean
 }
```


## Answer-path refactor: the composition layer the plan named, and one correction

**Timestamp:** 2026-08-12 14:30 -07:00

**AI tool:** Claude Code (Opus 5), used to audit the chat/messages/persistence flows
and execute the resulting refactor.

**1. Scope of the audit was narrowed against the AI's first read.** Asked to find what
was "messy" across chat, messages, and persistence, the useful finding was that
`persistence/`, `messages/`, `chat/context.py`, and `chat/generation.py` were already
clean — the mess was entirely *composition* duplicated across callers, and it lived
mostly in `api/`, which was not named in the request. The plan was written against the
evidence (four copies of one branch, two copies of one fold) rather than the named
directories, and reported that the named modules were fine. Recorded because "audit
these three things" would have produced three sets of cosmetic edits and left the
actual duplication untouched.

**2. `conversation/` as a new package, not `chat/pipeline.py`.** The AI's first
instinct was to keep the package count down by putting the composition in `chat/`. That
was rejected before implementing: it makes `chat/` import `retrieval.contract`, which
turns a self-contained generation package into a composer and inverts the dependency
direction `retrieval/` had already established. Both options were put to the user with
a recommendation; the new package was chosen. See `DESIGN_RECORDS.md` for the decision.

**3. A layering inversion the refactor introduced, caught and fixed mid-execution.**
`conversation/turn.py` was first written importing `AppClients` from `api/state.py` —
so the composition layer depended on the web layer, backwards. Fixed by moving the
composition root to `clients.py` at the backend root, leaving `app_clients(request)` in
`api/dependencies.py`. This also fixed a pre-existing inversion the move surfaced:
`eval/` had been importing `build_clients()` from `api.state` despite never serving
HTTP. Worth recording as the general shape of the mistake — a refactor that moves code
into a new layer will happily carry an old import with it, and the import is what tells
you the layer is wrong.

**4. Formatting left alone deliberately.** `ruff format --check` flagged six files;
five were pre-existing and CI does not run the formatter. Only the one file this work
created was formatted, rather than taking the "while we're here" reformat.

**Commit:** c231b77 (PR #17). Living-document updates are not in that commit; see the entry note.


## Rebase onto #16: the pre-stream failure test repointed at `prepare_turn`

**Timestamp:** 2026-08-12 14:52 -07:00

**AI tool:** Claude Code (Opus 5).

`api-contract-fixes` (#16) merged to `main` while the answer-path refactor (#17) was
being built, so the refactor branch was rebased onto it. Both of #16's changes survive
untouched — `ConversationDetail` stays flat, and the `OpenAIError` -> 502 handler stays
wired — because the refactor's diff never touched those regions.

One test did not survive, and CI caught it rather than review:
`tests/test_routes.py::test_an_openai_failure_before_the_stream_is_a_typed_502`
monkeypatched `api.routes.retrieve` to force a failure before the stream opens. That
function no longer exists; the handler now makes a single blocking call to
`prepare_turn`. The test was repointed at `api.routes.prepare_turn` and its fake changed
from `async def` to plain `def`, since `prepare_turn` is synchronous and offloaded with
`run_in_threadpool`. The assertion is unchanged, so it still proves the same thing: a
model failure before any token flows is an HTTP 502 the UI can render, not a broken
stream.

Recorded because it is the predictable cost of the refactor's central move. Collapsing
four call paths into one function means anything that reached into an intermediate step
by name has to be repointed, and a monkeypatched test is exactly that kind of reach.
The alternative reading — that the test was "broken by" the refactor — would be wrong:
the test's subject (the 502 contract) is intact, only its seam moved.

**Commit:** c231b77 (PR #17).
