"""The report renders every section and surfaces planted failures."""

from collections.abc import Callable

from eval.cases import EvalCase, ExpectedSource
from eval.judge import JudgeVerdict
from eval.report import render_report
from eval.trace import CaseTrace, ChunkTrace, EvalRun

MakeChunk = Callable[..., ChunkTrace]

CASES = [
    EvalCase(
        id="hit",
        question="q",
        kind="lookup",
        expected=[ExpectedSource(document_id="Warfarin", drug="warfarin", section_number="5.1")],
        expected_answer="a",
    ),
    EvalCase(id="advice", question="q", kind="advice", expected_answer="refusal"),
]


def trace(
    case_id: str, chunks: list[ChunkTrace], tags: list[str], config_name: str = "dense"
) -> CaseTrace:
    return CaseTrace(
        case_id=case_id,
        config_name=config_name,
        searched_query="q",
        refused=False,
        chunks=chunks,
        answer="answer [[S1]]",
        sources={},
        tags=tags,
        error=None,
    )


def test_report_renders_metrics_and_failures(make_chunk_trace: MakeChunk) -> None:
    run = EvalRun(
        started_at="2026-08-12T13:00:00-07:00",
        traces=[
            trace("hit", [make_chunk_trace()], tags=["S9"]),
            trace("advice", [], tags=[]),
        ],
    )
    verdicts = {
        ("hit", "dense"): JudgeVerdict(correct=True, grounded=True, reason="matches"),
        ("advice", "dense"): None,
    }
    report = render_report(CASES, run, verdicts)

    assert "## dense" in report
    assert "| strict/section | 1.00 | 1.00 |" in report  # the planted hit, top-ranked
    assert "advice question was not gate-refused" in report
    assert "hallucinated citation tags: S9" in report
    assert "unjudged: the judge call failed" in report
    # The only served chunk hits, so this query's chunk hit rate is a full bar.
    assert "hit  1.00  " + "#" * 24 in report


def test_comparison_ranks_the_configurations(make_chunk_trace: MakeChunk) -> None:
    """A configuration that retrieves nothing loses the metric and lands in the
    bottom band of the histogram; the winner is the one marked."""
    run = EvalRun(
        started_at="2026-08-12T13:00:00-07:00",
        traces=[
            trace("hit", [make_chunk_trace()], tags=[], config_name="dense"),
            trace("advice", [], tags=[], config_name="dense"),
            trace("hit", [make_chunk_trace(document_id="Other")], tags=[], config_name="sparse"),
            trace("advice", [], tags=[], config_name="sparse"),
        ],
    )
    report = render_report(CASES, run, {})

    assert "## Comparison" in report
    assert "| metric | dense | sparse |" in report
    assert "| Recall@5 (strict/section) | **1.00** | 0.00 |" in report
    # dense's one query sits in the top band, sparse's in the bottom.
    assert "  0.8-1.0  #                     1" in report
    assert "  0.0-0.2  #                     1" in report
