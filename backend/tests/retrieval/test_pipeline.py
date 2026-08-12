"""Pipeline composition: the toggles decide which tools run at all."""

from typing import cast

from openai import OpenAI

from retrieval.config import RetrievalConfig
from retrieval.pipeline import Proceed, prepare_query


def test_both_toggles_off_proceed_with_the_raw_query() -> None:
    client = cast(OpenAI, object())  # any attribute access would raise
    config = RetrievalConfig(gate=False, rewrite=False)
    assert prepare_query(client, "warfarin interactions", [], config) == Proceed(
        query="warfarin interactions"
    )
