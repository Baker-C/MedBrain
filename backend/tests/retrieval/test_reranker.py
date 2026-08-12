"""Reranker: scores reorder the candidates, and anything unusable keeps fused order."""

from collections.abc import Callable
from typing import NoReturn, cast

from openai import OpenAIError

from persistence.rows import ChunkRow
from retrieval.contract import ScoredChunk
from retrieval.ranking.reranker import (
    CandidateScore,
    RerankerModel,
    RerankScores,
    apply_scores,
    run_reranker,
)


def fused_candidates(make_chunk: Callable[[int], ChunkRow], count: int) -> list[ScoredChunk]:
    """`count` candidates already in RRF order, best first."""
    return [
        ScoredChunk(chunk=make_chunk(number), dense_rank=number, sparse_rank=None, rrf_score=1.0)
        for number in range(1, count + 1)
    ]


def rerank_scores(*pairs: tuple[int, int]) -> RerankScores:
    return RerankScores(scores=[CandidateScore(candidate=c, score=s) for c, s in pairs])


def test_scores_reorder_the_candidates(make_chunk: Callable[[int], ChunkRow]) -> None:
    ranked = apply_scores(fused_candidates(make_chunk, 3), rerank_scores((1, 2), (2, 9), (3, 5)))
    assert [scored.chunk.id for scored in ranked] == [2, 3, 1]
    assert [scored.rerank_score for scored in ranked] == [9, 5, 2]


def test_ties_keep_the_fused_order(make_chunk: Callable[[int], ChunkRow]) -> None:
    ranked = apply_scores(fused_candidates(make_chunk, 3), rerank_scores((1, 7), (2, 7), (3, 7)))
    assert [scored.chunk.id for scored in ranked] == [1, 2, 3]


def test_an_incomplete_response_keeps_the_fused_order(
    make_chunk: Callable[[int], ChunkRow],
) -> None:
    """Candidate 3 went unscored, so the whole response is unusable."""
    ranked = apply_scores(fused_candidates(make_chunk, 3), rerank_scores((1, 0), (2, 9)))
    assert [scored.chunk.id for scored in ranked] == [1, 2, 3]
    assert all(scored.rerank_score is None for scored in ranked)


def test_unparsed_output_keeps_the_fused_order(make_chunk: Callable[[int], ChunkRow]) -> None:
    candidates = fused_candidates(make_chunk, 3)
    assert apply_scores(candidates, None) == candidates


class _FailingModel:
    def invoke(self, messages: object) -> NoReturn:
        raise OpenAIError("api unreachable")


class _OffScheduleModel:
    """Structured output is schema-constrained in practice, but not by this code path."""

    def invoke(self, messages: object) -> object:
        return {"scores": "not the schema"}


def test_call_failure_fails_open(make_chunk: Callable[[int], ChunkRow]) -> None:
    candidates = fused_candidates(make_chunk, 3)
    ranked = run_reranker(cast(RerankerModel, _FailingModel()), "warfarin dosing", candidates)
    assert ranked == candidates


def test_output_off_the_schema_keeps_the_fused_order(
    make_chunk: Callable[[int], ChunkRow],
) -> None:
    candidates = fused_candidates(make_chunk, 3)
    ranked = run_reranker(cast(RerankerModel, _OffScheduleModel()), "warfarin dosing", candidates)
    assert ranked == candidates


def test_no_candidates_makes_no_call(make_chunk: Callable[[int], ChunkRow]) -> None:
    assert run_reranker(cast(RerankerModel, _FailingModel()), "warfarin dosing", []) == []
