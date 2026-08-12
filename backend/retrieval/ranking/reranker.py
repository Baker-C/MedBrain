"""LLM reranker: one batched pointwise call scores every fused candidate 0-10.

The model only scores; the ordering happens here, in code, so the numbers stay available
for the eval trace and the sort is reproducible. Anything short of one score per
candidate — a failed call, output that is not the expected schema, a partial or padded
list — leaves the fused order untouched, so a bad rerank degrades to RRF rather than to
nothing.

One call for the whole batch rather than one per candidate: 20 sequential calls would
dominate query latency, and pointwise scores are comparable enough for a sort at this
corpus size.
"""

from dataclasses import replace

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel

from prompts import RERANK
from retrieval.contract import ScoredChunk

RERANKER_MODEL = "gpt-5-nano"


class CandidateScore(BaseModel):
    candidate: int
    score: int


class RerankScores(BaseModel):
    scores: list[CandidateScore]


# `with_structured_output` is typed loosely — its output is narrowed in `run_reranker`
# rather than cast, so unexpected output takes the fail-open path already in the design.
RerankerModel = Runnable[LanguageModelInput, object]


def build_reranker() -> RerankerModel:
    """The configured reranker: gpt-5-nano constrained to the score schema.

    No temperature is set — the gpt-5 family only accepts its default. Determinism comes
    from the sort living in this module rather than from the sampler.
    """
    return ChatOpenAI(model=RERANKER_MODEL).with_structured_output(RerankScores)


def format_candidates(candidates: list[ScoredChunk]) -> str:
    """Number the candidates 1..N — small labels the model scores against, rather than
    database ids it might echo back wrongly."""
    return "\n\n".join(
        f"Candidate {number}:\n{scored.chunk.content}"
        for number, scored in enumerate(candidates, start=1)
    )


def build_rerank_messages(query: str, candidates: list[ScoredChunk]) -> list[BaseMessage]:
    return [
        SystemMessage(RERANK),
        HumanMessage(f"Query: {query}\n\n{format_candidates(candidates)}"),
    ]


def apply_scores(candidates: list[ScoredChunk], scores: RerankScores | None) -> list[ScoredChunk]:
    """Re-sort the candidates by score, highest first.

    The scores must cover every candidate number exactly once; a response that misses
    one, repeats one, or invents one is treated as unusable in whole and the fused order
    stands. Python's sort is stable, so equal scores keep RRF order.
    """
    if scores is None:
        return candidates
    by_candidate = {item.candidate: item.score for item in scores.scores}
    if sorted(by_candidate) != list(range(1, len(candidates) + 1)):
        return candidates
    ordered = sorted(
        ((by_candidate[number], scored) for number, scored in enumerate(candidates, start=1)),
        key=lambda scored_pair: -scored_pair[0],
    )
    return [replace(scored, rerank_score=score) for score, scored in ordered]


def run_reranker(
    model: RerankerModel, query: str, candidates: list[ScoredChunk]
) -> list[ScoredChunk]:
    """Adapter: fails open — an unusable rerank keeps the fused order."""
    if not candidates:
        return candidates
    try:
        parsed = model.invoke(build_rerank_messages(query, candidates))
    except OpenAIError:
        return candidates
    return apply_scores(candidates, parsed if isinstance(parsed, RerankScores) else None)
