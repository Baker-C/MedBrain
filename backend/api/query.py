"""The query endpoint's composition: retrieval, the chunk→document join, the event
stream, and the history writes, in order.

`run_retrieval` and every persistence call are blocking (sync psycopg, sync OpenAI
SDK), so each one is offloaded with `run_in_threadpool` — the endpoint streams on the
event loop and must never stall it. The assistant message is written when the stream
reaches `done`, before the event is yielded, so a failed write surfaces instead of
following a success signal; an errored stream persists nothing.
"""

from collections.abc import AsyncIterator
from uuid import UUID

import psycopg
from fastapi.concurrency import run_in_threadpool
from psycopg.rows import TupleRow
from pydantic import JsonValue

from api.join import attach_documents
from api.state import AppClients
from chat.answer import stream_answer_events, stream_canned_events
from chat.context import Citation, RetrievedChunk
from chat.events import DoneEvent, QueryEvent, SourcesEvent, TokenEvent, encode_sse
from persistence import conversations
from persistence.documents import fetch_documents
from retrieval.config import RetrievalConfig
from retrieval.contract import HistoryMessage, Refusal, Retrieved, ScoredChunk
from retrieval.pipeline import run_retrieval


def sources_snapshot(sources: dict[str, Citation]) -> dict[str, JsonValue]:
    """The tag→citation mapping as the jsonb value frozen onto the assistant message."""
    return {tag: citation.model_dump(mode="json") for tag, citation in sources.items()}


def load_retrieved(
    conn: psycopg.Connection[TupleRow], chunks: list[ScoredChunk]
) -> list[RetrievedChunk]:
    """The chunk→document join: one query for the parent documents, then the pure pairing."""
    documents = fetch_documents(conn, {scored.chunk.document_id for scored in chunks})
    return attach_documents(chunks, documents)


async def retrieve(
    clients: AppClients,
    conn: psycopg.Connection[TupleRow],
    question: str,
    history: list[HistoryMessage],
    config: RetrievalConfig,
) -> Refusal | Retrieved:
    """The blocking pipeline, offloaded once — gate through rerank in one call."""
    return await run_in_threadpool(
        run_retrieval,
        clients.openai,
        clients.embeddings,
        clients.reranker,
        conn,
        question,
        history,
        config,
    )


async def answer_events(
    clients: AppClients,
    conn: psycopg.Connection[TupleRow],
    conversation_id: UUID,
    result: Refusal | Retrieved,
) -> AsyncIterator[QueryEvent]:
    """The full answer stream with its history writes.

    A refusal streams canned events and persists as an assistant message with an empty
    sources mapping — a reader who never saw the stream still gets the same history. A
    retrieved result streams generation, accumulating the answer and its sources so the
    snapshot written at `done` matches exactly what the client saw.
    """
    if isinstance(result, Refusal):
        async for event in stream_canned_events(result.text):
            yield event
        await run_in_threadpool(
            conversations.append_message, conn, conversation_id, "assistant", result.text, {}
        )
        return

    retrieved = await run_in_threadpool(load_retrieved, conn, result.chunks)
    parts: list[str] = []
    sources: dict[str, Citation] = {}
    async for event in stream_answer_events(clients.generation, result.query, retrieved):
        match event:
            case SourcesEvent():
                sources = event.sources
            case TokenEvent():
                parts.append(event.text)
            case DoneEvent():
                await run_in_threadpool(
                    conversations.append_message,
                    conn,
                    conversation_id,
                    "assistant",
                    "".join(parts),
                    sources_snapshot(sources),
                )
        yield event


async def sse_frames(events: AsyncIterator[QueryEvent]) -> AsyncIterator[str]:
    """Each event as one encoded SSE frame, ready for a text/event-stream response."""
    async for event in events:
        yield encode_sse(event)
