"""The harness rewrites once per case, so configurations differ only in their toggle."""

from types import SimpleNamespace
from typing import cast

import pytest
from openai import OpenAI

from clients import AppClients
from eval import driver
from eval.cases import EvalCase
from eval.configs import EVAL_CONFIGS
from retrieval import pipeline
from retrieval.contract import HistoryMessage
from retrieval.pipeline import Proceed

CASE = EvalCase(
    id="lookup-trazodone-priapism",
    question="What does the trazodone labeling say about priapism?",
    kind="lookup",
    expected_answer="Priapism has been reported.",
)


@pytest.fixture
def rewrites(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A rewriter that answers differently every time — the real one's nondeterminism,
    made visible. The returned list records what it handed back."""
    given: list[str] = []

    def rewrite(client: OpenAI, query: str, history: list[HistoryMessage]) -> str:
        given.append(f"{query} [rewrite {len(given) + 1}]")
        return given[-1]

    monkeypatch.setattr(driver, "run_query_rewriter", rewrite)
    monkeypatch.setattr(pipeline, "run_query_rewriter", rewrite)
    monkeypatch.setattr(pipeline, "run_query_gate", lambda client, query, history: None)
    return given


def test_every_configuration_searches_the_one_shared_rewrite(rewrites: list[str]) -> None:
    clients = cast(AppClients, SimpleNamespace(openai=cast(OpenAI, object())))
    shared = driver.shared_rewrite(clients, CASE)

    searched = [
        pipeline.prepare_query(clients.openai, CASE.question, [], config, shared)
        for config in EVAL_CONFIGS.values()
    ]

    assert searched == [Proceed(query=shared)] * len(EVAL_CONFIGS)
    assert rewrites == [shared]
