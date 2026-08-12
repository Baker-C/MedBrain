"""Writing a turn's answer into history as its events go by.

A pass-through wrapper rather than a step in the pipeline, so persistence is something
a caller adds to a stream: the SSE endpoint wraps, the trace endpoint and the eval
harness do not, and neither path is a special case of the other.

The write happens when the stream reaches `done`, before that event is yielded, so a
failed write surfaces instead of following a success signal. An errored stream never
reaches `done` and so persists nothing — a partial answer is the client's to handle
via the error event, and never lands in shared history as if it were complete.
"""

from collections.abc import AsyncIterator
from uuid import UUID

import psycopg
from fastapi.concurrency import run_in_threadpool
from psycopg.rows import TupleRow

from chat.collect import Accumulator
from chat.contract import DoneEvent, QueryEvent
from conversation.history import append_answer


async def persist_on_done(
    events: AsyncIterator[QueryEvent],
    conn: psycopg.Connection[TupleRow],
    conversation_id: UUID,
) -> AsyncIterator[QueryEvent]:
    """The same events, with the answer they carry written to history when it completes.

    A refusal folds to its canned text and an empty mapping, so it persists like any
    other answer — a reader who never saw the stream still gets the same history.
    """
    accumulator = Accumulator()
    async for event in events:
        accumulator.add(event)
        if isinstance(event, DoneEvent):
            await run_in_threadpool(append_answer, conn, conversation_id, accumulator.collected())
        yield event
