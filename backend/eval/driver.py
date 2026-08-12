"""Drives one case through the real turn and records what happened.

The harness's pipeline I/O lives here and nowhere else. It calls `prepare_turn` — the
same function the query endpoint composes its response from — and deliberately skips
the endpoint's history writes, so a full run leaves no robot conversations in the
shared history (see DESIGN.md's eval-harness section).
"""

import asyncio

import psycopg
from psycopg.rows import TupleRow

from chat.collect import collect_answer
from chat.contract import RetrievedChunk
from clients import AppClients
from conversation.turn import prepare_turn
from eval.cases import EvalCase
from eval.trace import CaseTrace, ChunkTrace
from retrieval.config import RetrievalConfig
from retrieval.contract import ScoredChunk


def chunk_trace(scored: ScoredChunk, retrieved: RetrievedChunk) -> ChunkTrace:
    """One served chunk flattened into the run record: location from the chunk, drug
    from the joined document, scores from retrieval."""
    return ChunkTrace(
        document_id=scored.chunk.document_id,
        drug=retrieved.document.drug_name,
        section_number=scored.chunk.section_number,
        section_title=scored.chunk.section_title,
        page_start=scored.chunk.page_start,
        content=scored.chunk.content,
        dense_rank=scored.dense_rank,
        sparse_rank=scored.sparse_rank,
        rrf_score=scored.rrf_score,
        rerank_score=scored.rerank_score,
    )


def run_case(
    clients: AppClients,
    conn: psycopg.Connection[TupleRow],
    case: EvalCase,
    config_name: str,
    config: RetrievalConfig,
) -> CaseTrace:
    """One case under one configuration, end to end. Single-turn by design: the
    history is empty, so the rewriter only ever normalizes (see DESIGN.md).

    A refused case needs no special handling — it is a turn with no query and no
    chunks, whose answer is the refusal text that would have streamed.
    """
    turn = prepare_turn(clients, conn, case.question, [], config)
    answer = asyncio.run(collect_answer(turn.events))
    return CaseTrace(
        case_id=case.id,
        config_name=config_name,
        searched_query=turn.query,
        refused=turn.refused,
        chunks=[
            chunk_trace(scored, joined)
            for scored, joined in zip(turn.chunks, turn.retrieved, strict=True)
        ],
        answer=answer.answer,
        sources=answer.sources,
        tags=answer.tags,
        error=answer.error,
    )
