"""Route definitions: thin handlers that delegate to the feature packages.

Non-streaming handlers are plain `def` — FastAPI runs them on its threadpool, which
is the whole sync/async answer for endpoints that just hit the database. Only the
query endpoint is async, because it streams; its blocking work is `prepare_turn`,
offloaded in one call.
"""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg.rows import TupleRow

from api.dependencies import app_clients, db_connection
from api.models import (
    ConversationDetail,
    CreateConversationRequest,
    QueryRequest,
    SourceUrlResponse,
    TraceResponse,
    retrieval_config,
    traced_chunk,
)
from api.sse import sse_frames
from chat.collect import collect_answer
from conversation.history import append_question, conversation_history
from conversation.persist import persist_on_done
from conversation.turn import prepare_turn
from persistence import conversations
from persistence.documents import fetch_documents
from persistence.rows import ConversationRow
from persistence.storage import create_source_url

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
    """SSE by default; `?trace=true` runs the same turn but returns one JSON payload
    and skips every history write (the eval harness fires ~100+ requests)."""
    clients = app_clients(request)
    conversation = await run_in_threadpool(conversations.get_conversation, conn, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    prior = await run_in_threadpool(conversations.list_messages, conn, conversation_id)
    turn = await run_in_threadpool(
        prepare_turn,
        clients,
        conn,
        body.question,
        conversation_history(prior),
        retrieval_config(body),
    )

    if trace:
        return JSONResponse(
            TraceResponse(
                trace=await collect_answer(turn.events),
                query=turn.query,
                retrieval=[traced_chunk(scored) for scored in turn.chunks],
            ).model_dump(mode="json")
        )

    await run_in_threadpool(append_question, conn, conversation_id, body.question)
    return StreamingResponse(
        sse_frames(persist_on_done(turn.events, conn, conversation_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
