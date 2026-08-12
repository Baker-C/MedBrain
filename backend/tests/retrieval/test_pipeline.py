"""Pipeline composition: the toggles decide which tools run at all."""

from typing import cast

import psycopg
from openai import OpenAI
from psycopg.rows import TupleRow

from retrieval.config import RetrievalConfig
from retrieval.pipeline import Proceed, prepare_query, sparse_candidates


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
