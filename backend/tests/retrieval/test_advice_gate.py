"""Advice gate: verdicts map to refuse-or-pass, and the tool fails closed."""

from typing import NoReturn, cast

from openai import OpenAI, OpenAIError

from messages import GATE_UNAVAILABLE, PERSONAL_ADVICE_REFUSAL
from retrieval.contract import Refusal
from retrieval.query.advice_gate import (
    GateVerdict,
    interpret_gate_verdict,
    run_advice_gate,
)


def test_flagged_verdict_refuses() -> None:
    result = interpret_gate_verdict(GateVerdict(personal_advice=True))
    assert result == Refusal(text=PERSONAL_ADVICE_REFUSAL)


def test_unflagged_verdict_passes() -> None:
    assert interpret_gate_verdict(GateVerdict(personal_advice=False)) is None


class _FailingParse:
    def parse(self, **kwargs: object) -> NoReturn:
        raise OpenAIError("api unreachable")


class _FailingClient:
    class chat:
        completions = _FailingParse()


def test_call_failure_fails_closed() -> None:
    result = run_advice_gate(cast(OpenAI, _FailingClient()), "any question", [])
    assert result == Refusal(text=GATE_UNAVAILABLE)
