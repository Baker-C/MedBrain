"""History writes around the answer stream: a refusal and a done both persist one
assistant message, an errored stream persists nothing. This is the unit coverage
DESIGN.md promises in place of exercising trace mode against a live database."""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from langchain_core.language_models import BaseChatModel
from psycopg.rows import TupleRow
from pydantic import JsonValue

import conversation.history
from chat.contract import DoneEvent, ErrorEvent, QueryEvent, RetrievedChunk
from chat.stream import stream_answer_events, stream_canned_events
from conversation.persist import persist_on_done

MakeRetrieved = Callable[[], RetrievedChunk]
MakeModel = Callable[..., BaseChatModel]
WriteCall = tuple[str, str, dict[str, JsonValue] | None]


class Recorder:
    """Stands in for `append_message`, keeping what would have been written."""

    def __init__(self) -> None:
        self.calls: list[WriteCall] = []

    def __call__(
        self,
        conn: object,
        conversation_id: UUID,
        role: str,
        content: str,
        sources: dict[str, JsonValue] | None,
    ) -> None:
        self.calls.append((role, content, sources))


def run_persisted(
    monkeypatch: pytest.MonkeyPatch,
    events: AsyncIterator[QueryEvent],
    recorder: Recorder,
) -> list[QueryEvent]:
    """Drive a stream through `persist_on_done` with the database write faked out."""
    monkeypatch.setattr(conversation.history, "append_message", recorder)
    conn = cast(psycopg.Connection[TupleRow], object())

    async def gather() -> list[QueryEvent]:
        return [event async for event in persist_on_done(events, conn, uuid4())]

    return asyncio.run(gather())


def test_a_refusal_persists_as_an_assistant_message_with_empty_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History is shared and global — a reader who never saw the stream must still
    see the refusal text in the thread."""
    recorder = Recorder()
    events = run_persisted(monkeypatch, stream_canned_events("canned refusal"), recorder)

    assert isinstance(events[-1], DoneEvent)
    assert recorder.calls == [("assistant", "canned refusal", {})]


def test_done_persists_the_answer_with_its_sources_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    streaming_model: MakeModel,
    make_retrieved: MakeRetrieved,
) -> None:
    """The snapshot frozen at done must match exactly what the client streamed."""
    recorder = Recorder()
    model = streaming_model("Bleeding risk ", "is increased [[S1]].")
    stream = stream_answer_events(model, "q", [make_retrieved()])
    events = run_persisted(monkeypatch, stream, recorder)

    assert isinstance(events[-1], DoneEvent)
    (role, content, sources) = recorder.calls[0]
    assert role == "assistant"
    assert content == "Bleeding risk is increased [[S1]]."
    assert sources is not None and list(sources) == ["S1"]


def test_an_errored_stream_persists_no_assistant_message(
    monkeypatch: pytest.MonkeyPatch,
    failing_model: MakeModel,
    make_retrieved: MakeRetrieved,
) -> None:
    """A partial answer is the client's to handle via the error event; it never
    lands in shared history as if it were complete."""
    recorder = Recorder()
    stream = stream_answer_events(failing_model("partial "), "q", [make_retrieved()])
    events = run_persisted(monkeypatch, stream, recorder)

    assert isinstance(events[-1], ErrorEvent)
    assert recorder.calls == []
