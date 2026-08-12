"""Pipeline query preparation: with both toggles off, no tool and no LLM call runs."""

from typing import cast

from openai import OpenAI

from retrieval.pipeline import Proceed, prepare_query


def test_both_toggles_off_proceed_with_the_raw_query() -> None:
    client = cast(OpenAI, object())  # any attribute access would raise
    result = prepare_query(client, "warfarin interactions", [], gate=False, rewrite=False)
    assert result == Proceed(query="warfarin interactions")
