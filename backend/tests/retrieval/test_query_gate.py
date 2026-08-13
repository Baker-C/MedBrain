"""Query gate: each reason maps to its own refusal, and the tool fails closed."""

from typing import NoReturn, cast

import pytest
from openai import OpenAI, OpenAIError

from messages import (
    GATE_UNAVAILABLE,
    OFF_TOPIC_REFUSAL,
    PERSONAL_ADVICE_REFUSAL,
    UNSAFE_REQUEST_REFUSAL,
)
from retrieval.contract import Refusal
from retrieval.query.query_gate import (
    GateVerdict,
    RefusalReason,
    interpret_gate_verdict,
    run_query_gate,
)


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("personal_advice", PERSONAL_ADVICE_REFUSAL),
        ("unsafe", UNSAFE_REQUEST_REFUSAL),
        ("off_topic", OFF_TOPIC_REFUSAL),
    ],
)
def test_each_reason_refuses_in_its_own_words(reason: RefusalReason, text: str) -> None:
    assert interpret_gate_verdict(GateVerdict(reason=reason)) == Refusal(text=text)


def test_unflagged_verdict_passes() -> None:
    assert interpret_gate_verdict(GateVerdict(reason="none")) is None


class _FailingParse:
    def parse(self, **kwargs: object) -> NoReturn:
        raise OpenAIError("api unreachable")


class _FailingClient:
    class chat:
        completions = _FailingParse()


def test_call_failure_fails_closed() -> None:
    result = run_query_gate(cast(OpenAI, _FailingClient()), "any question", [])
    assert result == Refusal(text=GATE_UNAVAILABLE)
