"""Rank metrics on hand-built traces: the strict/lenient and document/section lenses."""

from collections.abc import Callable

from eval.cases import ExpectedSource
from eval.scoring.retrieval import precision_at_k, recall_at_k, reciprocal_rank
from eval.trace import ChunkTrace

MakeChunk = Callable[..., ChunkTrace]

WARFARIN_5_1 = [ExpectedSource(document_id="Warfarin", drug="warfarin", section_number="5.1")]


def test_sibling_label_counts_leniently_but_not_strictly(make_chunk_trace: MakeChunk) -> None:
    chunks = [make_chunk_trace(document_id="Warfarin_2")]
    assert recall_at_k(chunks, WARFARIN_5_1, 5, "lenient", "section") == 1.0
    assert recall_at_k(chunks, WARFARIN_5_1, 5, "strict", "section") == 0.0


def test_document_granularity_ignores_the_section(make_chunk_trace: MakeChunk) -> None:
    chunks = [make_chunk_trace(section_number="8.1")]
    assert recall_at_k(chunks, WARFARIN_5_1, 5, "strict", "document") == 1.0
    assert recall_at_k(chunks, WARFARIN_5_1, 5, "strict", "section") == 0.0


def test_expected_source_without_section_accepts_any_section(make_chunk_trace: MakeChunk) -> None:
    anywhere = [ExpectedSource(document_id="Warfarin", drug="warfarin")]
    chunks = [make_chunk_trace(section_number="17")]
    assert recall_at_k(chunks, anywhere, 5, "strict", "section") == 1.0


def test_recall_is_over_expected_sources(make_chunk_trace: MakeChunk) -> None:
    expected = [
        ExpectedSource(document_id="Warfarin", drug="warfarin", section_number="7"),
        ExpectedSource(document_id="Apixaban", drug="apixaban", section_number="7"),
    ]
    chunks = [make_chunk_trace(section_number="7")]
    assert recall_at_k(chunks, expected, 5, "strict", "section") == 0.5


def test_recall_respects_the_cutoff(make_chunk_trace: MakeChunk) -> None:
    chunks = [
        make_chunk_trace(document_id="Digoxin", drug="digoxin"),
        make_chunk_trace(document_id="Digoxin", drug="digoxin"),
        make_chunk_trace(),
    ]
    assert recall_at_k(chunks, WARFARIN_5_1, 2, "strict", "section") == 0.0
    assert recall_at_k(chunks, WARFARIN_5_1, 3, "strict", "section") == 1.0


def test_reciprocal_rank_reads_the_first_hit(make_chunk_trace: MakeChunk) -> None:
    chunks = [
        make_chunk_trace(document_id="Digoxin", drug="digoxin"),
        make_chunk_trace(document_id="Digoxin", drug="digoxin"),
        make_chunk_trace(),
    ]
    assert reciprocal_rank(chunks, WARFARIN_5_1, "strict", "section") == 1 / 3
    assert reciprocal_rank([], WARFARIN_5_1, "strict", "section") == 0.0


def test_precision_is_the_matching_share_of_the_served_top_k(make_chunk_trace: MakeChunk) -> None:
    chunks = [
        make_chunk_trace(),
        make_chunk_trace(document_id="Digoxin", drug="digoxin"),
        make_chunk_trace(),
        make_chunk_trace(document_id="Digoxin", drug="digoxin"),
    ]
    assert precision_at_k(chunks, WARFARIN_5_1, 4, "strict", "section") == 0.5
    assert precision_at_k(chunks[:1], WARFARIN_5_1, 4, "strict", "section") == 1.0
