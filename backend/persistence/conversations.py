"""Conversation history: the reads that rebuild a thread and the writes that extend it.

`messages.sources` is a write-once tag→citation snapshot, frozen at stream done and
read back whole. Connections are opened per request without autocommit, so the two
write adapters commit their own insert.
"""

from typing import Literal
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb
from pydantic import JsonValue

from persistence.db import fetch_rows
from persistence.rows import ConversationRow, MessageRow

# Selected from the row models themselves, so a query can never drift from what
# the model expects to validate.
CONVERSATION_COLUMNS = sql.SQL(", ").join(
    sql.Identifier(name) for name in ConversationRow.model_fields
)
MESSAGE_COLUMNS = sql.SQL(", ").join(sql.Identifier(name) for name in MessageRow.model_fields)

INSERT_CONVERSATION = sql.SQL(
    "insert into conversations (title) values (%s) returning {columns}"
).format(columns=CONVERSATION_COLUMNS)

SELECT_CONVERSATIONS = sql.SQL(
    "select {columns} from conversations order by created_at desc"
).format(columns=CONVERSATION_COLUMNS)

SELECT_CONVERSATION = sql.SQL("select {columns} from conversations where id = %s").format(
    columns=CONVERSATION_COLUMNS
)

SELECT_MESSAGES = sql.SQL(
    "select {columns} from messages where conversation_id = %s order by created_at"
).format(columns=MESSAGE_COLUMNS)

INSERT_MESSAGE = sql.SQL(
    "insert into messages (conversation_id, role, content, sources)"
    " values (%s, %s, %s, %s) returning {columns}"
).format(columns=MESSAGE_COLUMNS)


def create_conversation(conn: psycopg.Connection[TupleRow], title: str) -> ConversationRow:
    """Start a thread and return it as stored, with the id and timestamp the database set."""
    rows = fetch_rows(conn, INSERT_CONVERSATION, (title,), ConversationRow)
    conn.commit()
    return rows[0]


def list_conversations(conn: psycopg.Connection[TupleRow]) -> list[ConversationRow]:
    """Every thread, newest first — the order the sidebar shows them in."""
    return fetch_rows(conn, SELECT_CONVERSATIONS, (), ConversationRow)


def get_conversation(
    conn: psycopg.Connection[TupleRow], conversation_id: UUID
) -> ConversationRow | None:
    """One thread, or None when no thread has that id."""
    rows = fetch_rows(conn, SELECT_CONVERSATION, (conversation_id,), ConversationRow)
    return rows[0] if rows else None


def list_messages(conn: psycopg.Connection[TupleRow], conversation_id: UUID) -> list[MessageRow]:
    """A thread's messages in the order they were written."""
    return fetch_rows(conn, SELECT_MESSAGES, (conversation_id,), MessageRow)


def append_message(
    conn: psycopg.Connection[TupleRow],
    conversation_id: UUID,
    role: Literal["user", "assistant"],
    content: str,
    sources: dict[str, JsonValue] | None,
) -> MessageRow:
    """Add one message to a thread and return it as stored.

    `Jsonb` marks the snapshot as jsonb rather than a text parameter; a user message
    carries no sources and stores NULL.
    """
    payload = Jsonb(sources) if sources is not None else None
    rows = fetch_rows(conn, INSERT_MESSAGE, (conversation_id, role, content, payload), MessageRow)
    conn.commit()
    return rows[0]
