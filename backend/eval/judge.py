"""Eval-side answer scorer: a stronger model grades each answer against the case's
expected answer and the excerpts that were actually served.

Deliberately `gpt-5` — stronger than the generator, and not the generator's own model,
so self-preference bias does not inflate scores. It runs per eval run, never per user
query; the optional live-pipeline judge is a different, unbuilt thing (see DESIGN.md).
It fails open: a failed or off-schema call returns None and the report counts the case
as unjudged rather than dying sixty calls into a run.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel, SecretStr

from eval.cases import EvalCase
from eval.trace import CaseTrace, ChunkTrace
from prompts import EVAL_JUDGE

JUDGE_MODEL = "gpt-5"


class JudgeVerdict(BaseModel):
    """What the judge returns for one answer."""

    correct: bool  # agrees with the expected answer on the substance
    grounded: bool  # every claim is supported by the served excerpts
    reason: str  # one or two sentences; quoted in the report on failure


def build_judge(api_key: str) -> ChatOpenAI:
    """The judge model, built by its caller so the credential stays an explicit input."""
    return ChatOpenAI(model=JUDGE_MODEL, api_key=SecretStr(api_key))


def excerpt_block(position: int, chunk: ChunkTrace) -> str:
    """One served excerpt as the judge sees it, tagged the way the answer cites it."""
    heading = " - ".join(
        part
        for part in (chunk.drug, chunk.section_number, chunk.section_title)
        if part
    )
    return f"[[S{position + 1}]] {heading}\n{chunk.content}"


def judge_input(case: EvalCase, trace: CaseTrace) -> str:
    excerpts = (
        "\n\n".join(excerpt_block(position, chunk) for position, chunk in enumerate(trace.chunks))
        or "(no excerpts were served)"
    )
    return (
        f"Question: {case.question}\n\n"
        f"Expected answer: {case.expected_answer}\n\n"
        f"Served excerpts:\n{excerpts}\n\n"
        f"System's answer:\n{trace.answer}"
    )


def judge_answer(judge: BaseChatModel, case: EvalCase, trace: CaseTrace) -> JudgeVerdict | None:
    """One verdict, or None when the judge call fails or returns off-schema."""
    structured = judge.with_structured_output(JudgeVerdict)
    messages = [SystemMessage(content=EVAL_JUDGE), HumanMessage(content=judge_input(case, trace))]
    try:
        verdict = structured.invoke(messages)
    except OpenAIError:
        return None
    return verdict if isinstance(verdict, JudgeVerdict) else None
