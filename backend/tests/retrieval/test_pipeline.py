"""Pipeline composition: the toggles decide which tools run at all."""

from typing import cast

import psycopg
from openai import OpenAI
from psycopg.rows import TupleRow

from persistence.rows import ChunkRow
from retrieval.config import RetrievalConfig
from retrieval.contract import ScoredChunk
from retrieval.pipeline import Proceed, prepare_query, relevant_enough, sparse_candidates


def test_both_toggles_off_proceed_with_the_raw_query() -> None:
    client = cast(OpenAI, object())  # any attribute access would raise
    config = RetrievalConfig(gate=False, rewrite=False)
    assert prepare_query(client, "warfarin interactions", [], config) == Proceed(
        query="warfarin interactions"
    )


def test_sparse_toggled_off_skips_the_keyword_leg() -> None:
    conn = cast(psycopg.Connection[TupleRow], object())  # any query would raise
    config = RetrievalConfig(sparse=False)
    assert sparse_candidates(conn, "warfarin dosing", config) == []


def scored(rerank_score: int | None) -> ScoredChunk:
    return ScoredChunk(
        chunk=cast(ChunkRow, object()),  # the filter reads scores, never the chunk
        dense_rank=1,
        sparse_rank=None,
        rrf_score=0.0,
        rerank_score=rerank_score,
    )


def test_a_chunk_below_the_minimum_is_dropped() -> None:
    assert not relevant_enough(scored(2), 3)


def test_a_chunk_at_the_minimum_is_kept() -> None:
    assert relevant_enough(scored(3), 3)


def test_an_unscored_chunk_is_kept() -> None:
    """The reranker was off or its call failed; neither is the chunk's fault."""
    assert relevant_enough(scored(None), 3)
