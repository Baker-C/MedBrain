"""The chunk→document bridge: each chunk keeps its own parent, and a missing one raises."""

from datetime import UTC, datetime

import pytest

from api.join import attach_documents
from persistence.rows import ChunkRow, DocumentRow
from retrieval.contract import ScoredChunk


def make_document(document_id: str, drug: str) -> DocumentRow:
    return DocumentRow(
        id=document_id,
        storage_object_key=f"documents/{document_id}.pdf",
        file_sha256="a" * 64,
        drug_name=drug,
        manufacturer="Teva Pharmaceuticals USA",
        formulation=None,
        chunk_count=1,
        ingested_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
    )


def make_scored_chunk(chunk_id: int, document_id: str) -> ScoredChunk:
    chunk = ChunkRow(
        id=chunk_id,
        document_id=document_id,
        content=f"chunk {chunk_id}",
        content_sha256=f"{chunk_id:064x}",
        section_number="5.1",
        section_title="Hemorrhage",
        page_start=1,
        page_end=1,
        chunk_index=0,
        chunk_type="text",
    )
    return ScoredChunk(chunk=chunk, dense_rank=1, sparse_rank=None, rrf_score=0.5)


def test_each_chunk_is_paired_with_its_own_document_in_retrieved_order() -> None:
    chunks = [
        make_scored_chunk(1, "Warfarin_2"),
        make_scored_chunk(2, "Metformin_1"),
        make_scored_chunk(3, "Warfarin_2"),
    ]
    documents = {
        "Warfarin_2": make_document("Warfarin_2", "warfarin"),
        "Metformin_1": make_document("Metformin_1", "metformin"),
    }

    retrieved = attach_documents(chunks, documents)

    assert [item.chunk.id for item in retrieved] == [1, 2, 3]
    assert [item.document.drug_name for item in retrieved] == ["warfarin", "metformin", "warfarin"]


def test_a_chunk_whose_document_is_absent_raises() -> None:
    """The foreign key guarantees the parent exists, so absence is corruption, not a
    chunk to quietly drop from the answer."""
    with pytest.raises(KeyError):
        attach_documents([make_scored_chunk(1, "Warfarin_2")], {})
