"""History writes around the answer stream: a refusal and a done both persist one
assistant message, an errored stream persists nothing. This is the unit coverage
DESIGN.md promises in place of exercising trace mode against a live database."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from langchain_core.messages import AIMessageChunk
from openai import OpenAIError
from psycopg.rows import TupleRow
from pydantic import JsonValue

import api.query
from api.query import answer_events
from api.state import AppClients
from chat.context import RetrievedChunk
from chat.events import DoneEvent, ErrorEvent, QueryEvent
from persistence import conversations
from persistence.rows import ChunkRow, DocumentRow
from retrieval.contract import Refusal, Retrieved, ScoredChunk

SnapshotCall = tuple[str, str, dict[str, JsonValue] | None]


class _Recorder:
    """Stands in for `append_message`, keeping what would have been written."""

    def __init__(self) -> None:
        self.calls: list[SnapshotCall] = []

    def __call__(
        self,
        conn: object,
        conversation_id: UUID,
        role: str,
        content: str,
        sources: dict[str, JsonValue] | None,
    ) -> None:
        self.calls.append((role, content, sources))


class _StreamingModel:
    """Yields the given deltas; only `astream` is reached from chat/."""

    def __init__(self, *deltas: str) -> None:
        self._deltas = deltas

    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        for delta in self._deltas:
            yield AIMessageChunk(content=delta)


class _FailingMidStream:
    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content="partial ")
        raise OpenAIError("connection lost")


def make_scored() -> ScoredChunk:
    return ScoredChunk(
        chunk=ChunkRow(
            id=1,
            document_id="Warfarin_2",
            content="Bleeding risk is increased.",
            content_sha256="b" * 64,
            section_number="5.1",
            section_title="Hemorrhage",
            page_start=12,
            page_end=12,
            chunk_index=0,
            chunk_type="text",
        ),
        dense_rank=1,
        sparse_rank=None,
        rrf_score=0.016,
    )


def make_document() -> DocumentRow:
    return DocumentRow(
        id="Warfarin_2",
        storage_object_key="documents/Warfarin_2.pdf",
        file_sha256="a" * 64,
        drug_name="warfarin",
        manufacturer="Teva Pharmaceuticals USA",
        formulation=None,
        chunk_count=1,
        ingested_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
    )


def run_stream(
    monkeypatch: pytest.MonkeyPatch,
    model: object,
    result: Refusal | Retrieved,
    recorder: _Recorder,
) -> list[QueryEvent]:
    """Drive `answer_events` with the persistence write and document join faked out."""
    monkeypatch.setattr(conversations, "append_message", recorder)
    scored = result.chunks if isinstance(result, Retrieved) else []
    retrieved = [
        RetrievedChunk(chunk=item.chunk, document=make_document()) for item in scored
    ]
    monkeypatch.setattr(
        api.query, "load_retrieved", lambda conn, chunks: retrieved
    )
    clients = cast(AppClients, type("_Clients", (), {"generation": model})())
    conn = cast(psycopg.Connection[TupleRow], object())

    async def gather() -> list[QueryEvent]:
        return [event async for event in answer_events(clients, conn, uuid4(), result)]

    return asyncio.run(gather())


def test_a_refusal_persists_as_an_assistant_message_with_empty_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History is shared and global — a reader who never saw the stream must still
    see the refusal text in the thread."""
    recorder = _Recorder()
    events = run_stream(monkeypatch, object(), Refusal(text="canned refusal"), recorder)

    assert isinstance(events[-1], DoneEvent)
    assert recorder.calls == [("assistant", "canned refusal", {})]


def test_done_persists_the_answer_with_its_sources_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The snapshot frozen at done must match exactly what the client streamed."""
    recorder = _Recorder()
    model = _StreamingModel("Bleeding risk ", "is increased [[S1]].")
    events = run_stream(
        monkeypatch, model, Retrieved(query="q", chunks=[make_scored()]), recorder
    )

    assert isinstance(events[-1], DoneEvent)
    (role, content, sources) = recorder.calls[0]
    assert role == "assistant"
    assert content == "Bleeding risk is increased [[S1]]."
    assert sources is not None and list(sources) == ["S1"]


def test_an_errored_stream_persists_no_assistant_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial answer is the client's to handle via the error event; it never
    lands in shared history as if it were complete."""
    recorder = _Recorder()
    events = run_stream(
        monkeypatch, _FailingMidStream(), Retrieved(query="q", chunks=[make_scored()]), recorder
    )

    assert isinstance(events[-1], ErrorEvent)
    assert recorder.calls == []
