"""Folding an event stream back into the answer it carried.

Written once and used twice, because the two uses must not disagree: the history
write freezes the fold onto the assistant message, and the eval harness scores it.
`Accumulator` is fed event by event as a stream passes through, so a caller that is
also serving those events does not have to buffer or replay them; `collect_answer`
is the same fold over a stream nobody else is watching.
"""

from collections.abc import AsyncIterator

from chat.context import emitted_tags
from chat.contract import (
    Citation,
    CollectedAnswer,
    DoneEvent,
    ErrorEvent,
    QueryEvent,
    SourcesEvent,
    TokenEvent,
)


class Accumulator:
    """Builds the finished answer from the events as they go by."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._sources: dict[str, Citation] = {}
        self._error: str | None = None

    def add(self, event: QueryEvent) -> None:
        match event:
            case SourcesEvent():
                self._sources = event.sources
            case TokenEvent():
                self._parts.append(event.text)
            case ErrorEvent():
                self._error = event.message
            case DoneEvent():
                pass

    def collected(self) -> CollectedAnswer:
        answer = "".join(self._parts)
        return CollectedAnswer(
            answer=answer,
            sources=self._sources,
            tags=emitted_tags(answer),
            error=self._error,
        )


async def collect_answer(events: AsyncIterator[QueryEvent]) -> CollectedAnswer:
    """Drain a stream nobody else is consuming, and return what it said."""
    accumulator = Accumulator()
    async for event in events:
        accumulator.add(event)
    return accumulator.collected()
