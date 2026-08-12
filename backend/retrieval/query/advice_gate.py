"""Medical-advice gate: refuses questions that seek personal medical advice.

One structured-output call on the raw query plus conversation history. Fails
closed: if the call cannot run, the query is refused rather than answered
ungated.
"""

from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from messages import GATE_UNAVAILABLE, PERSONAL_ADVICE_REFUSAL
from prompts import ADVICE_GATE
from retrieval.contract import HistoryMessage, Refusal
from retrieval.query.transcript import build_user_prompt

ADVICE_GATE_MODEL = "gpt-5-mini"


class GateVerdict(BaseModel):
    personal_advice: bool


def build_gate_messages(
    query: str, history: list[HistoryMessage]
) -> list[ChatCompletionMessageParam]:
    return [
        {"role": "system", "content": ADVICE_GATE},
        {"role": "user", "content": build_user_prompt(query, history)},
    ]


def interpret_gate_verdict(verdict: GateVerdict) -> Refusal | None:
    """A refusal for a flagged question; None lets the query proceed."""
    if verdict.personal_advice:
        return Refusal(text=PERSONAL_ADVICE_REFUSAL)
    return None


def run_advice_gate(
    client: OpenAI, query: str, history: list[HistoryMessage]
) -> Refusal | None:
    """Adapter: fails closed — an ungateable query is refused, not answered."""
    try:
        completion = client.chat.completions.parse(
            model=ADVICE_GATE_MODEL,
            messages=build_gate_messages(query, history),
            response_format=GateVerdict,
        )
    except OpenAIError:
        return Refusal(text=GATE_UNAVAILABLE)
    verdict = completion.choices[0].message.parsed
    if verdict is None:
        return Refusal(text=GATE_UNAVAILABLE)
    return interpret_gate_verdict(verdict)
