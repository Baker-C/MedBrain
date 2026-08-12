"""Context assembly: tags are positional, citations join chunk to document, sections degrade."""

from datetime import UTC, datetime

from chat.context import (
    Citation,
    RetrievedChunk,
    build_context,
    build_sources,
    citation_for,
    emitted_tags,
)
from persistence.rows import ChunkRow, DocumentRow


def make_document(document_id: str = "Warfarin_2", drug: str = "warfarin") -> DocumentRow:
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


def make_chunk(
    content: str = "Bleeding risk is increased.",
    section_number: str | None = "5.1",
    section_title: str | None = "Hemorrhage",
    page_start: int = 12,
) -> ChunkRow:
    return ChunkRow(
        id=1,
        document_id="Warfarin_2",
        content=content,
        content_sha256="b" * 64,
        section_number=section_number,
        section_title=section_title,
        page_start=page_start,
        page_end=page_start,
        chunk_index=0,
        chunk_type="text",
    )


def test_citation_joins_document_identity_to_chunk_location() -> None:
    retrieved = RetrievedChunk(chunk=make_chunk(), document=make_document())
    assert citation_for(retrieved) == Citation(
        document_id="Warfarin_2",
        drug="warfarin",
        section_number="5.1",
        section_title="Hemorrhage",
        page_start=12,
    )


def test_sectionless_chunk_still_cites_document_and_page() -> None:
    retrieved = RetrievedChunk(
        chunk=make_chunk(section_number=None, section_title=None),
        document=make_document(),
    )
    citation = citation_for(retrieved)
    assert (citation.section_number, citation.section_title) == (None, None)
    assert (citation.document_id, citation.page_start) == ("Warfarin_2", 12)


def test_tags_are_positional_and_shared_by_the_mapping_and_the_context() -> None:
    chunks = [
        RetrievedChunk(chunk=make_chunk(content="first"), document=make_document()),
        RetrievedChunk(chunk=make_chunk(content="second"), document=make_document()),
    ]
    sources = build_sources(chunks)
    context = build_context(chunks)

    assert list(sources) == ["S1", "S2"]
    assert "[[S1]] warfarin - 5.1 Hemorrhage\nfirst" in context
    assert "[[S2]] warfarin - 5.1 Hemorrhage\nsecond" in context


def test_context_heading_omits_a_missing_section() -> None:
    chunks = [
        RetrievedChunk(
            chunk=make_chunk(content="body", section_number=None, section_title=None),
            document=make_document(),
        )
    ]
    assert build_context(chunks) == "[[S1]] warfarin\nbody"


def test_emitted_tags_are_deduplicated_in_order_of_first_appearance() -> None:
    answer = "Warfarin raises bleeding risk [[S2]]. Monitor INR [[S1]]. Also [[S2]]."
    assert emitted_tags(answer) == ["S2", "S1"]


def test_no_tags_in_an_uncited_answer() -> None:
    assert emitted_tags("The provided labeling does not cover that.") == []
