"""Hashing, indexing, and the page floor."""

import pytest

from errors import IngestionError
from models import DraftChunk
from stamping import content_sha256, stamp_chunks
from tests.factories import draft


def test_indexes_chunks_in_order() -> None:
    stamped = stamp_chunks([draft("First."), draft("Second."), draft("Third.")])

    assert [chunk.chunk_index for chunk in stamped] == [0, 1, 2]


def test_location_is_outside_the_hash() -> None:
    # A revised label that moves a paragraph must relocate it, not re-embed it.
    assert content_sha256(draft("Same text.", page=4).content) == content_sha256(
        draft("Same text.", page=9).content
    )


def test_content_repeated_inside_one_document_collapses_to_one_chunk() -> None:
    # `UNIQUE (document_id, content_sha256)` means the second copy is the same row.
    stamped = stamp_chunks([draft("Same text.", page=4), draft("Same text.", page=9)])

    assert len(stamped) == 1
    assert stamped[0].page_start == 4


@pytest.mark.parametrize("pages", [(0, 0), (5, 4), (-1, 3)])
def test_an_unresolvable_page_span_fails_loudly(pages: tuple[int, int]) -> None:
    page_start, page_end = pages
    unplaceable = DraftChunk(
        content="Hemorrhage can occur at any site.",
        section_number="5.1",
        section_title="Hemorrhage",
        page_start=page_start,
        page_end=page_end,
        chunk_type="text",
    )

    with pytest.raises(IngestionError, match="citation floor"):
        stamp_chunks([unplaceable])
