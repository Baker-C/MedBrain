"""The chunk→document bridge: each chunk keeps its own parent, and a missing one raises."""

from collections.abc import Callable

import pytest

from chat.join import attach_documents
from persistence.rows import ChunkRow, DocumentRow
from retrieval.contract import ScoredChunk

MakeChunk = Callable[..., ChunkRow]
MakeDocument = Callable[..., DocumentRow]


def make_scored(make_chunk: MakeChunk, chunk_id: int, document_id: str) -> ScoredChunk:
    return ScoredChunk(
        chunk=make_chunk(chunk_id, document_id=document_id),
        dense_rank=1,
        sparse_rank=None,
        rrf_score=0.5,
    )


def test_each_chunk_is_paired_with_its_own_document_in_retrieved_order(
    make_chunk: MakeChunk, make_document: MakeDocument
) -> None:
    chunks = [
        make_scored(make_chunk, 1, "Warfarin_2"),
        make_scored(make_chunk, 2, "Metformin_1"),
        make_scored(make_chunk, 3, "Warfarin_2"),
    ]
    documents = {
        "Warfarin_2": make_document("Warfarin_2", "warfarin"),
        "Metformin_1": make_document("Metformin_1", "metformin"),
    }

    retrieved = attach_documents(chunks, documents)

    assert [item.chunk.id for item in retrieved] == [1, 2, 3]
    assert [item.document.drug_name for item in retrieved] == ["warfarin", "metformin", "warfarin"]


def test_a_chunk_whose_document_is_absent_raises(make_chunk: MakeChunk) -> None:
    """The foreign key guarantees the parent exists, so absence is corruption, not a
    chunk to quietly drop from the answer."""
    with pytest.raises(KeyError):
        attach_documents([make_scored(make_chunk, 1, "Warfarin_2")], {})
