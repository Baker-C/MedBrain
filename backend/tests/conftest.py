"""Fixtures shared by the retrieval tests."""

from collections.abc import Callable

import pytest

from persistence.rows import ChunkRow


@pytest.fixture
def make_chunk() -> Callable[[int], ChunkRow]:
    """Build a minimal valid chunk row. Ranking tests care only about identity, so
    everything except the id is filler that satisfies the model."""

    def build(chunk_id: int) -> ChunkRow:
        return ChunkRow(
            id=chunk_id,
            document_id="warfarin_1",
            content=f"chunk {chunk_id}",
            content_sha256=f"{chunk_id:064x}",
            section_number="5",
            section_title="WARNINGS AND PRECAUTIONS",
            page_start=1,
            page_end=1,
            chunk_index=chunk_id,
            chunk_type="text",
        )

    return build
