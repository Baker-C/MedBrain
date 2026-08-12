"""What a resolved turn looks like to whoever asked for it."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from chat.contract import QueryEvent, RetrievedChunk
from retrieval.contract import ScoredChunk


@dataclass(frozen=True)
class Turn:
    """One question resolved: what retrieval decided, and the answer that follows from it.

    Deliberately carries no `Refusal | Retrieved` — a refusal is a turn whose query is
    None and whose chunks are empty, and whose events are the canned stream. Callers
    therefore never branch on the outcome; they read the fields they need. The branch
    happens once, in `prepare_turn`.

    `events` is a live stream and can be consumed once. `chunks` and `retrieved` are
    parallel: the same chunks, with and without the scores they earned.
    """

    query: str | None
    refused: bool
    chunks: list[ScoredChunk]
    retrieved: list[RetrievedChunk]
    events: AsyncIterator[QueryEvent]
