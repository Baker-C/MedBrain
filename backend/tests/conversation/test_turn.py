"""The one place a refusal is told apart from a retrieved result.

Every caller reads the same `Turn` fields afterwards, so these two shapes are what
the SSE endpoint, the trace endpoint, and the eval harness all see.
"""

import asyncio
from collections.abc import Callable
from typing import cast

import psycopg
import pytest
from langchain_core.language_models import BaseChatModel
from psycopg.rows import TupleRow

import conversation.turn
from chat.collect import collect_answer
from chat.contract import RetrievedChunk
from clients import AppClients
from conversation.contract import Turn
from conversation.turn import prepare_turn
from persistence.rows import ChunkRow
from retrieval.config import RetrievalConfig
from retrieval.contract import Refusal, Retrieved, ScoredChunk

MakeChunk = Callable[..., ChunkRow]
MakeRetrieved = Callable[[], RetrievedChunk]
MakeModel = Callable[..., BaseChatModel]


def make_turn(
    monkeypatch: pytest.MonkeyPatch,
    result: Refusal | Retrieved,
    retrieved: list[RetrievedChunk],
    model: BaseChatModel | None = None,
) -> Turn:
    """Run `prepare_turn` with retrieval and the document join faked out."""
    monkeypatch.setattr(conversation.turn, "run_retrieval", lambda *args, **kwargs: result)
    monkeypatch.setattr(conversation.turn, "load_retrieved", lambda conn, chunks: retrieved)
    stub = {"generation": model, "openai": None, "embeddings": None, "reranker": None}
    clients = cast(AppClients, type("Clients", (), stub)())
    conn = cast(psycopg.Connection[TupleRow], object())
    return prepare_turn(clients, conn, "question", [], RetrievalConfig())


def test_a_refusal_is_a_turn_with_no_query_and_nothing_retrieved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = make_turn(monkeypatch, Refusal(text="canned refusal"), [])

    assert (turn.query, turn.refused) == (None, True)
    assert (turn.chunks, turn.retrieved) == ([], [])
    assert asyncio.run(collect_answer(turn.events)).answer == "canned refusal"


def test_a_retrieved_result_carries_the_searched_query_and_its_chunks(
    monkeypatch: pytest.MonkeyPatch,
    make_chunk: MakeChunk,
    make_retrieved: MakeRetrieved,
    streaming_model: MakeModel,
) -> None:
    """`chunks` and `retrieved` stay parallel — the eval harness zips them strictly."""
    scored = ScoredChunk(chunk=make_chunk(1), dense_rank=1, sparse_rank=None, rrf_score=0.5)
    turn = make_turn(
        monkeypatch,
        Retrieved(query="rewritten query", chunks=[scored]),
        [make_retrieved()],
        streaming_model("Bleeding risk is increased [[S1]]."),
    )

    assert (turn.query, turn.refused) == ("rewritten query", False)
    assert len(turn.chunks) == len(turn.retrieved) == 1
    assert asyncio.run(collect_answer(turn.events)).answer == "Bleeding risk is increased [[S1]]."
