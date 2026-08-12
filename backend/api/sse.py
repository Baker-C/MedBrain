"""Server-sent events: how a `QueryEvent` reaches the wire.

Transport only, and the one place the wire format is decided. The chat package owns
what an event *is*; this owns how it is framed, so a change of transport touches
nothing but this module.
"""

from collections.abc import AsyncIterator

from chat.contract import QueryEvent


def encode_sse(event: QueryEvent) -> str:
    """One SSE frame. The payload is JSON so newlines in answer text cannot break framing."""
    return f"event: {event.name}\ndata: {event.model_dump_json()}\n\n"


async def sse_frames(events: AsyncIterator[QueryEvent]) -> AsyncIterator[str]:
    """Each event as one encoded frame, ready for a text/event-stream response."""
    async for event in events:
        yield encode_sse(event)
