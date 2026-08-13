"""Query gate: refuses a question before anything is embedded or retrieved.

One structured-output call on the raw query plus conversation history returns one
reason, and each reason has its own pre-written refusal — a harm-seeking question and
an off-topic one must not be told they asked for personal medical advice. Fails
closed: if the call cannot run, the query is refused rather than answered ungated.
"""

from typing import Literal

from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from messages import (
    GATE_UNAVAILABLE,
    OFF_TOPIC_REFUSAL,
    PERSONAL_ADVICE_REFUSAL,
    UNSAFE_REQUEST_REFUSAL,
)
from prompts import QUERY_GATE
from retrieval.contract import HistoryMessage, Refusal
from retrieval.query.transcript import build_user_prompt

QUERY_GATE_MODEL = "gpt-5-mini"

RefusalReason = Literal["none", "personal_advice", "unsafe", "off_topic"]

REFUSAL_TEXT: dict[RefusalReason, str] = {
    "personal_advice": PERSONAL_ADVICE_REFUSAL,
    "unsafe": UNSAFE_REQUEST_REFUSAL,
    "off_topic": OFF_TOPIC_REFUSAL,
}


class GateVerdict(BaseModel):
    reason: RefusalReason


def build_gate_messages(
    query: str, history: list[HistoryMessage]
) -> list[ChatCompletionMessageParam]:
    return [
        {"role": "system", "content": QUERY_GATE},
        {"role": "user", "content": build_user_prompt(query, history)},
    ]


def interpret_gate_verdict(verdict: GateVerdict) -> Refusal | None:
    """The refusal this reason earns; None lets the query proceed."""
    text = REFUSAL_TEXT.get(verdict.reason)
    return Refusal(text=text) if text is not None else None


def run_query_gate(client: OpenAI, query: str, history: list[HistoryMessage]) -> Refusal | None:
    """Adapter: fails closed — an ungateable query is refused, not answered."""
    try:
        completion = client.chat.completions.parse(
            model=QUERY_GATE_MODEL,
            messages=build_gate_messages(query, history),
            response_format=GateVerdict,
        )
    except OpenAIError:
        return Refusal(text=GATE_UNAVAILABLE)
    verdict = completion.choices[0].message.parsed
    if verdict is None:
        return Refusal(text=GATE_UNAVAILABLE)
    return interpret_gate_verdict(verdict)
