"""The SSE event contract: the four event payloads and their wire encoding.

Pure logic, no I/O. Emission order is `sources` first (so the client holds the
tag→citation mapping before any sentinel arrives), then `token`s carrying raw model
text, then `done` or `error`. Tokens are never rewritten: sentinels pass through
exactly as the model emitted them and the client buffers ones split across events.
"""

from typing import ClassVar

from pydantic import BaseModel

from chat.context import Citation


class SourcesEvent(BaseModel):
    """First event of every stream: the tags the answer may cite, and what they mean."""

    name: ClassVar[str] = "sources"

    sources: dict[str, Citation]


class TokenEvent(BaseModel):
    """One piece of answer text, exactly as the model produced it."""

    name: ClassVar[str] = "token"

    text: str


class DoneEvent(BaseModel):
    """End of a successful stream, carrying post-hoc annotations.

    `judge_grounded` is the slot the optional live judge fills; it stays None until
    that step exists.
    """

    name: ClassVar[str] = "done"

    judge_grounded: bool | None = None


class ErrorEvent(BaseModel):
    """Failure at any point, including partway through a stream. Terminates it."""

    name: ClassVar[str] = "error"

    message: str


QueryEvent = SourcesEvent | TokenEvent | DoneEvent | ErrorEvent


def encode_sse(event: QueryEvent) -> str:
    """One SSE frame. The payload is JSON so newlines in answer text cannot break framing."""
    return f"event: {event.name}\ndata: {event.model_dump_json()}\n\n"
