"""Query rewriter: usable rewrites are used, everything else falls back to the raw query."""

from typing import NoReturn, cast

from openai import OpenAI, OpenAIError

from retrieval.query.query_rewriter import QueryRewrite, choose_query, run_query_rewriter


def test_usable_rewrite_is_chosen() -> None:
    rewrite = QueryRewrite(rewritten_query="warfarin bleeding warnings")
    assert choose_query(rewrite, "what about bleeding?") == "warfarin bleeding warnings"


def test_empty_rewrite_falls_back_to_the_raw_query() -> None:
    assert choose_query(QueryRewrite(rewritten_query=""), "warfarin interactions") == (
        "warfarin interactions"
    )


def test_missing_rewrite_falls_back_to_the_raw_query() -> None:
    assert choose_query(None, "warfarin interactions") == "warfarin interactions"


class _FailingParse:
    def parse(self, **kwargs: object) -> NoReturn:
        raise OpenAIError("api unreachable")


class _FailingClient:
    class chat:
        completions = _FailingParse()


def test_call_failure_fails_open_to_the_raw_query() -> None:
    result = run_query_rewriter(cast(OpenAI, _FailingClient()), "warfarin interactions", [])
    assert result == "warfarin interactions"
