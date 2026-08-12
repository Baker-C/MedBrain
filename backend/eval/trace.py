"""What one case run leaves behind: the harness's unit of record.

`CaseTrace` carries everything scoring and the judge need, and an `EvalRun` of them
is saved to `eval/runs/<timestamp>.json` so a run can be re-scored offline without
re-spending a single model call. The shapes mirror the pipeline's own (`ScoredChunk`,
the citation mapping) but are models rather than dataclasses because they cross a
file boundary and are validated on reload.
"""

from pydantic import BaseModel

from chat.contract import Citation


class ChunkTrace(BaseModel):
    """One served chunk: where it came from, what it said, and the scores it earned.

    Ranks and scores read as in `ScoredChunk`: a rank is None when that leg did not
    run or did not return the chunk; `rerank_score` is None when the reranker was off
    or its output was discarded whole. `content` is kept so the judge can re-read the
    excerpts from a saved run.
    """

    document_id: str
    drug: str
    section_number: str | None
    section_title: str | None
    page_start: int
    content: str
    dense_rank: int | None
    sparse_rank: int | None
    rrf_score: float
    rerank_score: int | None


class CaseTrace(BaseModel):
    """One case under one configuration, end to end.

    `searched_query` is what the search legs actually used — rewritten or raw — and
    None when the gate refused before any search ran. A refusal's text lands in
    `answer`, since that is what would have streamed.
    """

    case_id: str
    config_name: str
    searched_query: str | None
    refused: bool
    chunks: list[ChunkTrace]
    answer: str
    sources: dict[str, Citation]
    tags: list[str]
    error: str | None = None


class EvalRun(BaseModel):
    """A whole run as saved to `eval/runs/`: every case under every configuration."""

    started_at: str
    traces: list[CaseTrace]
