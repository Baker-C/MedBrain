"""The vocabulary retrieval speaks to its callers.

Everything that crosses the package boundary lives here: what goes in
(`HistoryMessage`), what comes back when the pipeline stops early (`Refusal`), and the
scored chunk a result is made of.
Callers import this module and nothing deeper — the stage packages are internal.
Purely declarative: no I/O, and no dependency beyond the row models.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from persistence.rows import ChunkRow


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Refusal:
    """The pipeline stopped before retrieving anything; `text` is what streams instead."""

    text: str


@dataclass(frozen=True)
class ScoredChunk:
    """A chunk plus what it earned on the way through the pipeline.

    A rank is None when that leg did not run, or ran and did not return the chunk.
    `rerank_score` is None whenever the reranker was off or its output was unusable.
    """

    chunk: ChunkRow
    dense_rank: int | None
    sparse_rank: int | None
    rrf_score: float
    rerank_score: int | None = None
