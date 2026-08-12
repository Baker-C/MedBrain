"""Request and response shapes for the API layer.

Row models serialize directly as responses — re-declaring them here would be
drift-prone duplication — so this module holds only what the wire needs beyond
them: the two request bodies, the composite conversation view, and the trace
payload the eval harness consumes.
"""

from pydantic import BaseModel

from chat.answer import AnswerTrace
from persistence.rows import ConversationRow, MessageRow
from retrieval.config import RetrievalConfig
from retrieval.contract import ScoredChunk


class CreateConversationRequest(BaseModel):
    title: str


class QueryRequest(BaseModel):
    """A question plus the four pipeline toggles.

    Toggles default to what in-app traffic runs; the eval harness varies them one
    at a time. The cut-offs are deliberately not request parameters.
    """

    question: str
    gate: bool = True
    rewrite: bool = True
    sparse: bool = True
    rerank: bool = True


def retrieval_config(request: QueryRequest) -> RetrievalConfig:
    """The pipeline config a request asks for; cut-offs stay at their defaults."""
    return RetrievalConfig(
        gate=request.gate,
        rewrite=request.rewrite,
        sparse=request.sparse,
        rerank=request.rerank,
    )


class ConversationDetail(BaseModel):
    """One conversation with its full message history, oldest first."""

    conversation: ConversationRow
    messages: list[MessageRow]


class SourceUrlResponse(BaseModel):
    url: str


class TracedChunk(BaseModel):
    """One retrieved chunk's identity and the scores it earned, for the eval trace."""

    chunk_id: int
    document_id: str
    section_number: str | None
    section_title: str | None
    page_start: int
    dense_rank: int | None
    sparse_rank: int | None
    rrf_score: float
    rerank_score: int | None


def traced_chunk(scored: ScoredChunk) -> TracedChunk:
    return TracedChunk(
        chunk_id=scored.chunk.id,
        document_id=scored.chunk.document_id,
        section_number=scored.chunk.section_number,
        section_title=scored.chunk.section_title,
        page_start=scored.chunk.page_start,
        dense_rank=scored.dense_rank,
        sparse_rank=scored.sparse_rank,
        rrf_score=scored.rrf_score,
        rerank_score=scored.rerank_score,
    )


class TraceResponse(BaseModel):
    """What `?trace=true` returns: the answer as users would get it, plus the
    retrieval trace the eval harness scores. `retrieval` is empty on a refusal."""

    trace: AnswerTrace
    query: str | None
    retrieval: list[TracedChunk]
