"""Context assembly: tags are positional, citations join chunk to document, sections degrade."""

from collections.abc import Callable

from chat.context import build_context, build_sources, citation_for, emitted_tags
from chat.contract import Citation, RetrievedChunk
from persistence.rows import ChunkRow, DocumentRow

MakeChunk = Callable[..., ChunkRow]
MakeDocument = Callable[..., DocumentRow]


def test_citation_joins_document_identity_to_chunk_location(
    make_chunk: MakeChunk, make_document: MakeDocument
) -> None:
    chunk = make_chunk(1, section_number="5.1", section_title="Hemorrhage", page_start=12)
    retrieved = RetrievedChunk(chunk=chunk, document=make_document())
    assert citation_for(retrieved) == Citation(
        document_id="Warfarin_2",
        drug="warfarin",
        section_number="5.1",
        section_title="Hemorrhage",
        page_start=12,
    )


def test_sectionless_chunk_still_cites_document_and_page(
    make_chunk: MakeChunk, make_document: MakeDocument
) -> None:
    chunk = make_chunk(1, section_number=None, section_title=None, page_start=12)
    citation = citation_for(RetrievedChunk(chunk=chunk, document=make_document()))
    assert (citation.section_number, citation.section_title) == (None, None)
    assert (citation.document_id, citation.page_start) == ("Warfarin_2", 12)


def test_tags_are_positional_and_shared_by_the_mapping_and_the_context(
    make_chunk: MakeChunk, make_document: MakeDocument
) -> None:
    chunks = [
        RetrievedChunk(
            chunk=make_chunk(1, content=content, section_number="5.1", section_title="Hemorrhage"),
            document=make_document(),
        )
        for content in ("first", "second")
    ]
    sources = build_sources(chunks)
    context = build_context(chunks)

    assert list(sources) == ["S1", "S2"]
    assert "[[S1]] warfarin - 5.1 Hemorrhage\nfirst" in context
    assert "[[S2]] warfarin - 5.1 Hemorrhage\nsecond" in context


def test_context_heading_omits_a_missing_section(
    make_chunk: MakeChunk, make_document: MakeDocument
) -> None:
    chunk = make_chunk(1, content="body", section_number=None, section_title=None)
    chunks = [RetrievedChunk(chunk=chunk, document=make_document())]
    assert build_context(chunks) == "[[S1]] warfarin\nbody"


def test_emitted_tags_are_deduplicated_in_order_of_first_appearance() -> None:
    answer = "Warfarin raises bleeding risk [[S2]]. Monitor INR [[S1]]. Also [[S2]]."
    assert emitted_tags(answer) == ["S2", "S1"]


def test_no_tags_in_an_uncited_answer() -> None:
    assert emitted_tags("The provided labeling does not cover that.") == []
