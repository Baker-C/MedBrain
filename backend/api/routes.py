"""Route definitions: thin handlers that delegate to the feature packages.

Non-streaming handlers are plain `def` — FastAPI runs them on its threadpool, which
is the whole sync/async answer for endpoints that just hit the database. Only the
query endpoint is async, because it streams; its blocking work is offloaded inside
`api.query`.
"""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg.rows import TupleRow

from api.dependencies import db_connection
from api.models import (
    ConversationDetail,
    CreateConversationRequest,
    QueryRequest,
    SourceUrlResponse,
    TraceResponse,
    retrieval_config,
    traced_chunk,
)
from api.query import answer_events, load_retrieved, retrieve, sse_frames
from api.state import AppClients, app_clients
from chat.answer import AnswerTrace, trace_answer
from persistence import conversations
from persistence.documents import fetch_documents
from persistence.rows import ConversationRow
from persistence.storage import create_source_url
from retrieval.contract import HistoryMessage, Refusal, Retrieved

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/conversations")
def create_conversation(
    body: CreateConversationRequest,
    conn: psycopg.Connection[TupleRow] = Depends(db_connection),
) -> ConversationRow:
    return conversations.create_conversation(conn, body.title)


@router.get("/conversations")
def list_conversations(
    conn: psycopg.Connection[TupleRow] = Depends(db_connection),
) -> list[ConversationRow]:
    return conversations.list_conversations(conn)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    conn: psycopg.Connection[TupleRow] = Depends(db_connection),
) -> ConversationDetail:
    conversation = conversations.get_conversation(conn, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationDetail(
        **conversation.model_dump(),
        messages=conversations.list_messages(conn, conversation_id),
    )


@router.get("/documents/{document_id}/source-url")
def get_source_url(
    document_id: str,
    request: Request,
    conn: psycopg.Connection[TupleRow] = Depends(db_connection),
) -> SourceUrlResponse:
    documents = fetch_documents(conn, {document_id})
    if document_id not in documents:
        raise HTTPException(status_code=404, detail="document not found")
    storage = app_clients(request).storage
    object_key = documents[document_id].storage_object_key
    return SourceUrlResponse(url=create_source_url(storage, object_key))


@router.post("/conversations/{conversation_id}/query", response_model=None)
async def query(
    conversation_id: UUID,
    body: QueryRequest,
    request: Request,
    trace: bool = False,
    conn: psycopg.Connection[TupleRow] = Depends(db_connection),
) -> StreamingResponse | JSONResponse:
    """SSE by default; `?trace=true` runs the same pipeline but returns one JSON
    payload and skips every history write (the eval harness fires ~100+ requests)."""
    clients = app_clients(request)
    conversation = await run_in_threadpool(conversations.get_conversation, conn, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    prior = await run_in_threadpool(conversations.list_messages, conn, conversation_id)
    history = [HistoryMessage(role=message.role, content=message.content) for message in prior]
    result = await retrieve(clients, conn, body.question, history, retrieval_config(body))

    if trace:
        return JSONResponse(
            (await build_trace(clients, conn, result)).model_dump(mode="json")
        )

    await run_in_threadpool(
        conversations.append_message, conn, conversation_id, "user", body.question, None
    )
    return StreamingResponse(
        sse_frames(answer_events(clients, conn, conversation_id, result)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def build_trace(
    clients: AppClients,
    conn: psycopg.Connection[TupleRow],
    result: Refusal | Retrieved,
) -> TraceResponse:
    """The trace payload: a refusal is its canned text with nothing retrieved; a
    retrieved result is the real answer path collected into one payload."""
    if isinstance(result, Refusal):
        return TraceResponse(
            trace=AnswerTrace(answer=result.text, sources={}, tags=[]),
            query=None,
            retrieval=[],
        )
    retrieved = await run_in_threadpool(load_retrieved, conn, result.chunks)
    answer = await trace_answer(clients.generation, result.query, retrieved)
    return TraceResponse(
        trace=answer,
        query=result.query,
        retrieval=[traced_chunk(scored) for scored in result.chunks],
    )
