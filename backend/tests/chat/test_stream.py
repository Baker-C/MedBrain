"""Event stream: order, the no-context short circuit, and mid-stream failure."""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import cast

from langchain_core.language_models import BaseChatModel

from chat.contract import (
    DoneEvent,
    ErrorEvent,
    QueryEvent,
    RetrievedChunk,
    SourcesEvent,
    TokenEvent,
)
from chat.stream import stream_answer_events
from messages import ANSWER_UNAVAILABLE, NO_SUPPORTING_CONTEXT

MakeRetrieved = Callable[[], RetrievedChunk]
MakeModel = Callable[..., BaseChatModel]


def drain(events: AsyncIterator[QueryEvent]) -> list[QueryEvent]:
    async def gather() -> list[QueryEvent]:
        return [event async for event in events]

    return asyncio.run(gather())


def test_mapping_arrives_before_any_token_and_done_closes_the_stream(
    streaming_model: MakeModel, make_retrieved: MakeRetrieved
) -> None:
    model = streaming_model("Bleeding risk ", "is increased [[S1]].")
    events = drain(stream_answer_events(model, "warfarin bleeding risk", [make_retrieved()]))

    assert [type(event) for event in events] == [SourcesEvent, TokenEvent, TokenEvent, DoneEvent]
    first = events[0]
    assert isinstance(first, SourcesEvent)
    assert list(first.sources) == ["S1"]
    assert first.sources["S1"].drug == "warfarin"


def test_no_chunks_streams_the_canned_message_without_calling_the_model() -> None:
    model = cast(BaseChatModel, object())  # any attribute access would raise
    events = drain(stream_answer_events(model, "what does metformin do?", []))

    assert [type(event) for event in events] == [SourcesEvent, TokenEvent, DoneEvent]
    sources, token = events[0], events[1]
    assert isinstance(sources, SourcesEvent) and sources.sources == {}
    assert isinstance(token, TokenEvent) and token.text == NO_SUPPORTING_CONTEXT


def test_failure_partway_through_ends_in_error_not_done(
    failing_model: MakeModel, make_retrieved: MakeRetrieved
) -> None:
    model = failing_model("Warfarin raises bleeding risk [[S1]]")
    events = drain(stream_answer_events(model, "warfarin bleeding risk", [make_retrieved()]))

    assert [type(event) for event in events] == [SourcesEvent, TokenEvent, ErrorEvent]
    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.message == ANSWER_UNAVAILABLE
