"""Translating between stored messages and what the two packages want to see.

Stored history is `MessageRow`s; retrieval wants `HistoryMessage`s and knows nothing
about the database. An assistant message stores a tag→citation snapshot; the shape of
that snapshot is the streaming contract's, and this is where it is pinned down —
`MessageRow.sources` can only say `dict[str, JsonValue]`, because persistence must not
depend on `chat/`.
"""

from uuid import UUID

import psycopg
from psycopg.rows import TupleRow
from pydantic import JsonValue

from chat.contract import Citation, CollectedAnswer
from persistence.conversations import append_message
from persistence.rows import MessageRow
from retrieval.contract import HistoryMessage


def conversation_history(messages: list[MessageRow]) -> list[HistoryMessage]:
    """A stored thread as the transcript the query stage reads."""
    return [HistoryMessage(role=message.role, content=message.content) for message in messages]


def sources_snapshot(sources: dict[str, Citation]) -> dict[str, JsonValue]:
    """The tag→citation mapping as the jsonb value frozen onto an assistant message."""
    return {tag: citation.model_dump(mode="json") for tag, citation in sources.items()}


def append_answer(
    conn: psycopg.Connection[TupleRow], conversation_id: UUID, answer: CollectedAnswer
) -> None:
    """Store a finished answer as the thread's next assistant message."""
    append_message(
        conn, conversation_id, "assistant", answer.answer, sources_snapshot(answer.sources)
    )


def append_question(
    conn: psycopg.Connection[TupleRow], conversation_id: UUID, question: str
) -> None:
    """Store the asked question. A user message carries no sources."""
    append_message(conn, conversation_id, "user", question, None)
