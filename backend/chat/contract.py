"""The vocabulary the chat package speaks to its callers.

Everything that crosses the package boundary lives here: what goes in
(`RetrievedChunk`), what comes out (the four events and the `CollectedAnswer` a
finished stream folds into), and the `Citation` both of those carry. Callers import
this module and nothing deeper — `context`, `generation`, `stream`, and `collect`
are internal. Purely declarative: no I/O, and no dependency beyond the row models.

The events are the streaming contract itself. Emission order is `sources` first (so
the client holds the tag->citation mapping before any sentinel arrives), then
`token`s carrying raw model text, then `done` or `error`. Tokens are never
rewritten: sentinels pass through exactly as the model emitted them and the client
buffers ones split across events. How an event reaches the wire is the API layer's
business, not this package's.
"""

from dataclasses import dataclass
from typing import ClassVar, Protocol

from pydantic import BaseModel

from persistence.rows import ChunkRow


class CitedDocument(Protocol):
    """The document fields a citation needs. `DocumentRow` satisfies this structurally,
    so `chat/` sees only these two and a rename in the row model fails the type check."""

    id: str
    drug_name: str


@dataclass(frozen=True)
class RetrievedChunk:
    """One chunk retrieval selected, with the document it belongs to.

    An in-process handoff of rows already validated at the retrieval adapter, so it is
    a dataclass rather than a model — the same shape `Refusal` and `Proceed` use.
    """

    chunk: ChunkRow
    document: CitedDocument


class Citation(BaseModel):
    """One resolved source, sent in the `sources` event and frozen into `messages.sources`.

    Section fields degrade to null on a chunk with no carved section; `page_start` is
    the guaranteed floor every citation deep-links to.
    """

    document_id: str
    drug: str
    section_number: str | None
    section_title: str | None
    page_start: int


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


class CollectedAnswer(BaseModel):
    """A finished stream folded back into one value: the answer and its citations.

    Two callers need this and must not disagree — the history write freezes it onto
    the assistant message, and the eval harness scores it. `tags` are the sentinels the
    answer really emitted, which the harness checks against `sources` to confirm every
    citation resolves to a chunk that was actually retrieved.
    """

    answer: str
    sources: dict[str, Citation]
    tags: list[str]
    error: str | None = None
