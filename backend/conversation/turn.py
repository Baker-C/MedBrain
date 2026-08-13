"""Composes retrieval, the chunk→document join, and generation into one turn.

This is the only place the two outcomes retrieval can return are told apart. Every
caller — the SSE endpoint, the trace endpoint, the eval harness — goes through here,
so the harness measures the path users actually get rather than a parallel one.

Blocking throughout (sync psycopg, sync OpenAI SDK), and sync on purpose: an async
caller offloads the whole thing with one `run_in_threadpool`, and the eval harness
calls it directly. Building the event stream is not itself blocking; consuming it is
what makes the model call, and that is async.
"""

import psycopg
from psycopg.rows import TupleRow

from chat.join import load_retrieved
from chat.stream import stream_answer_events, stream_canned_events
from clients import AppClients
from conversation.contract import Turn
from retrieval.config import RetrievalConfig
from retrieval.contract import HistoryMessage, Refusal
from retrieval.pipeline import run_retrieval


def prepare_turn(
    clients: AppClients,
    conn: psycopg.Connection[TupleRow],
    question: str,
    history: list[HistoryMessage],
    config: RetrievalConfig,
    rewritten_query: str | None = None,
) -> Turn:
    """Run the question through retrieval and hand back the answer stream it earned.

    A refusal never reaches generation: its text streams as canned events, which fold
    back to the same shape a generated answer does.

    `rewritten_query` reuses a rewrite computed elsewhere, which is how the eval
    harness holds the searched query steady across configurations; see
    `retrieval.pipeline.prepare_query`.
    """
    result = run_retrieval(
        clients.openai,
        clients.embeddings,
        clients.reranker,
        conn,
        question,
        history,
        config,
        rewritten_query,
    )
    if isinstance(result, Refusal):
        return Turn(
            query=None,
            refused=True,
            chunks=[],
            retrieved=[],
            events=stream_canned_events(result.text),
        )
    retrieved = load_retrieved(conn, result.chunks)
    return Turn(
        query=result.query,
        refused=False,
        chunks=result.chunks,
        retrieved=retrieved,
        events=stream_answer_events(clients.generation, result.query, retrieved),
    )
