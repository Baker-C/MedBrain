"""Pass 2: per-section splitting, repeated headings, and where pages come from."""

import pytest

from errors import IngestionError
from models import Section
from splitting import Segment, pages_for_span, split_section, split_sections
from tests.factories import table, text

TABLE_HTML = "<table><tr><th>INR</th><th>Dose</th></tr><tr><td>2.0</td><td>5 mg</td></tr></table>"


def words(prefix: str, count: int = 600) -> str:
    """Distinct tokens, so a chunk's provenance and its overlap are both visible."""
    return " ".join(f"{prefix}{index}" for index in range(count))


def test_sub_chunks_never_cross_a_section_boundary() -> None:
    sections = [
        Section("5.1", "Hemorrhage", (text(words("a"), page=8),)),
        Section("5.2", "Tissue Necrosis", (text(words("b"), page=9),)),
    ]

    chunks = split_sections(sections)

    assert len(chunks) > 2
    for chunk in chunks:
        foreign = "b1 " if chunk.section_number == "5.1" else "a1 "
        assert foreign not in chunk.content


def test_every_sub_chunk_repeats_its_section_heading() -> None:
    chunks = split_section(Section("5.1", "Hemorrhage", (text(words("a"), page=8),)))

    assert len(chunks) > 1
    assert all(chunk.content.startswith("5.1 Hemorrhage\n\n") for chunk in chunks)


def test_overlap_exists_inside_a_subdivided_section() -> None:
    chunks = split_section(Section("5.1", "Hemorrhage", (text(words("a"), page=8),)))
    bodies = [chunk.content.removeprefix("5.1 Hemorrhage\n\n") for chunk in chunks]

    assert bodies[1].split()[0] in bodies[0]


def test_an_unnumbered_section_repeats_its_title_alone() -> None:
    section = Section(None, "WARNING: BLEEDING RISK", (text("Warfarin can cause bleeding."),))

    assert split_section(section)[0].content.startswith("WARNING: BLEEDING RISK\n\n")


def test_page_span_covers_every_element_a_chunk_touches() -> None:
    section = Section(
        "6", "Adverse Reactions", (text("First part.", page=4), text("Second part.", page=5))
    )

    chunks = split_section(section)

    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (4, 5)


def test_a_chunk_that_maps_to_no_page_is_an_error() -> None:
    with pytest.raises(IngestionError, match="citation floor"):
        pages_for_span([Segment(0, 10, 4, 4)], 20, 30)


def test_a_table_is_its_own_chunk_and_keeps_its_stitched_page_span() -> None:
    section = Section(
        "12.3",
        "Pharmacokinetics",
        (text("Warfarin is metabolized by CYP2C9.", page=17), table(TABLE_HTML, page=17,
                                                                   page_end=18)),
    )

    chunks = split_section(section)

    assert [chunk.chunk_type for chunk in chunks] == ["text", "table"]
    assert (chunks[1].page_start, chunks[1].page_end) == (17, 18)
    assert chunks[1].content == "12.3 Pharmacokinetics\n\nINR | Dose\n2.0 | 5 mg"


def test_prose_before_and_after_a_table_stays_in_document_order() -> None:
    section = Section(
        "12.3",
        "Pharmacokinetics",
        (text("Before the table.", page=17), table(TABLE_HTML, page=17),
         text("After the table.", page=17)),
    )

    chunks = split_section(section)

    assert [chunk.chunk_type for chunk in chunks] == ["text", "table", "text"]
    assert "Before the table." in chunks[0].content
    assert "After the table." in chunks[2].content
