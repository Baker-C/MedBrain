"""Event stream: order, the no-context short circuit, mid-stream failure, and trace collection."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from openai import OpenAIError

from chat.answer import stream_answer_events, trace_answer
from chat.context import RetrievedChunk
from chat.events import DoneEvent, ErrorEvent, QueryEvent, SourcesEvent, TokenEvent
from messages import ANSWER_UNAVAILABLE, NO_SUPPORTING_CONTEXT
from persistence.rows import ChunkRow, DocumentRow


def make_retrieved(content: str = "Bleeding risk is increased.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk=ChunkRow(
            id=1,
            document_id="Warfarin_2",
            content=content,
            content_sha256="b" * 64,
            section_number="5.1",
            section_title="Hemorrhage",
            page_start=12,
            page_end=12,
            chunk_index=0,
            chunk_type="text",
        ),
        document=DocumentRow(
            id="Warfarin_2",
            storage_object_key="documents/Warfarin_2.pdf",
            file_sha256="a" * 64,
            drug_name="warfarin",
            manufacturer="Teva Pharmaceuticals USA",
            formulation=None,
            chunk_count=1,
            ingested_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        ),
    )


class _StreamingModel:
    """Yields the given deltas. Only `astream` is reached from chat/."""

    def __init__(self, *deltas: str) -> None:
        self._deltas = deltas

    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        for delta in self._deltas:
            yield AIMessageChunk(content=delta)


class _FailingMidStream:
    """Streams part of an answer, then the connection drops."""

    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content="Warfarin raises bleeding risk [[S1]]")
        raise OpenAIError("connection lost")


def collect(events: AsyncIterator[QueryEvent]) -> list[QueryEvent]:
    async def gather() -> list[QueryEvent]:
        return [event async for event in events]

    return asyncio.run(gather())


def test_mapping_arrives_before_any_token_and_done_closes_the_stream() -> None:
    model = cast(BaseChatModel, _StreamingModel("Bleeding risk ", "is increased [[S1]]."))
    events = collect(stream_answer_events(model, "warfarin bleeding risk", [make_retrieved()]))

    assert [type(event) for event in events] == [SourcesEvent, TokenEvent, TokenEvent, DoneEvent]
    first = events[0]
    assert isinstance(first, SourcesEvent)
    assert list(first.sources) == ["S1"]
    assert first.sources["S1"].drug == "warfarin"


def test_no_chunks_streams_the_canned_message_without_calling_the_model() -> None:
    model = cast(BaseChatModel, object())  # any attribute access would raise
    events = collect(stream_answer_events(model, "what does metformin do?", []))

    assert [type(event) for event in events] == [SourcesEvent, TokenEvent, DoneEvent]
    sources, token = events[0], events[1]
    assert isinstance(sources, SourcesEvent) and sources.sources == {}
    assert isinstance(token, TokenEvent) and token.text == NO_SUPPORTING_CONTEXT


def test_failure_partway_through_ends_in_error_not_done() -> None:
    model = cast(BaseChatModel, _FailingMidStream())
    events = collect(stream_answer_events(model, "warfarin bleeding risk", [make_retrieved()]))

    assert [type(event) for event in events] == [SourcesEvent, TokenEvent, ErrorEvent]
    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.message == ANSWER_UNAVAILABLE


def test_trace_collects_the_same_stream_into_one_payload() -> None:
    model = cast(BaseChatModel, _StreamingModel("Bleeding risk ", "is increased [[S1]]."))
    trace = asyncio.run(trace_answer(model, "warfarin bleeding risk", [make_retrieved()]))

    assert trace.answer == "Bleeding risk is increased [[S1]]."
    assert trace.tags == ["S1"]
    assert list(trace.sources) == ["S1"]
    assert trace.error is None


def test_trace_records_a_mid_stream_failure() -> None:
    model = cast(BaseChatModel, _FailingMidStream())
    trace = asyncio.run(trace_answer(model, "warfarin bleeding risk", [make_retrieved()]))

    assert trace.error == ANSWER_UNAVAILABLE
    assert trace.answer == "Warfarin raises bleeding risk [[S1]]"
