"""Pass 2: split each carved section on its own, so no chunk can cross a boundary.

The recursive splitter only ever sees one section's text, which is what makes
cross-section bleed impossible by construction rather than by rule. Overlap is a
splitter setting, so it is confined to the same section for the same reason. Every
chunk repeats its section heading, so the embedded text carries its own context.

Pages are not guessed. Each element contributes a segment to the joined section text,
and a chunk's page span is read from the segments its character range covers — the
splitter reports that range via `add_start_index`. A chunk whose range maps to no
segment raises rather than shipping a citation that cannot be clicked.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from errors import IngestionError
from models import DraftChunk, PageElement, Section
from tables import parse_table, split_table

CHUNK_TARGET_CHARS = 1500
CHUNK_OVERLAP_CHARS = 150
# Floor under the splitter budget, so a long heading cannot shrink chunks to nothing.
MIN_CHUNK_CHARS = 400
SEGMENT_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class Segment:
    """One element's span inside the joined section text, and the pages it came from."""

    start: int
    end: int
    page_start: int
    page_end: int


def section_heading(section: Section) -> str:
    return " ".join(part for part in (section.number, section.title) if part)


def heading_prefix(section: Section) -> str:
    heading = section_heading(section)
    return f"{heading}\n\n" if heading else ""


def chunk_budget(prefix: str) -> int:
    """Room left for content once the repeated heading is accounted for."""
    return max(MIN_CHUNK_CHARS, CHUNK_TARGET_CHARS - len(prefix))


def join_text_elements(elements: Sequence[PageElement]) -> tuple[str, list[Segment]]:
    parts: list[str] = []
    segments: list[Segment] = []
    cursor = 0
    for element in elements:
        text = element.text.strip()
        if not text:
            continue
        if parts:
            cursor += len(SEGMENT_SEPARATOR)
        segments.append(Segment(cursor, cursor + len(text), element.page_start, element.page_end))
        parts.append(text)
        cursor += len(text)
    return SEGMENT_SEPARATOR.join(parts), segments


def pages_for_span(segments: Sequence[Segment], start: int, end: int) -> tuple[int, int]:
    """Page span of every element the chunk touches. Empty overlap is an error, not a default."""
    covered = [s for s in segments if s.start < end and start < s.end]
    if not covered:
        raise IngestionError(
            f"Chunk at characters {start}-{end} maps to no page; page is the citation floor."
        )
    return min(s.page_start for s in covered), max(s.page_end for s in covered)


def start_index_of(metadata: dict[str, object]) -> int:
    """Read the splitter's reported offset, refusing anything that is not one."""
    start = metadata.get("start_index")
    if not isinstance(start, int) or start < 0:
        raise IngestionError(f"Splitter reported no usable start index: {start!r}")
    return start


def build_splitter(budget: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=budget,
        chunk_overlap=min(CHUNK_OVERLAP_CHARS, budget // 4),
        add_start_index=True,
        # Offsets must address the text that was passed in, so whitespace stays put
        # until the chunk content is built.
        strip_whitespace=False,
    )


def split_text_elements(section: Section, elements: Sequence[PageElement]) -> list[DraftChunk]:
    text, segments = join_text_elements(elements)
    if not text.strip():
        return []

    prefix = heading_prefix(section)
    budget = chunk_budget(prefix)
    chunks: list[DraftChunk] = []
    for document in build_splitter(budget).create_documents([text]):
        content = document.page_content.strip()
        if not content:
            continue
        start = start_index_of(document.metadata)
        page_start, page_end = pages_for_span(
            segments, start, start + len(document.page_content)
        )
        chunks.append(
            DraftChunk(
                content=prefix + content,
                section_number=section.number,
                section_title=section.title,
                page_start=page_start,
                page_end=page_end,
                chunk_type="text",
            )
        )
    return chunks


def split_table_element(section: Section, element: PageElement) -> list[DraftChunk]:
    """A table is atomic: it is never merged with prose, and only ever cut between rows."""
    prefix = heading_prefix(section)
    grid = parse_table(element.html) if element.html else None
    pieces = (
        split_table(grid, chunk_budget(prefix))
        if grid is not None and (grid.header or grid.rows)
        else [element.text.strip()]
    )
    return [
        DraftChunk(
            content=prefix + piece,
            section_number=section.number,
            section_title=section.title,
            page_start=element.page_start,
            page_end=element.page_end,
            chunk_type="table",
        )
        for piece in pieces
        if piece
    ]


def split_section(section: Section) -> list[DraftChunk]:
    """Prose runs split; tables branch off whole. Element order is preserved."""
    chunks: list[DraftChunk] = []
    run: list[PageElement] = []
    for element in section.elements:
        if element.kind == "table":
            chunks.extend(split_text_elements(section, run))
            run = []
            chunks.extend(split_table_element(section, element))
        else:
            run.append(element)
    chunks.extend(split_text_elements(section, run))
    return chunks


def split_sections(sections: Sequence[Section]) -> list[DraftChunk]:
    return [chunk for section in sections for chunk in split_section(section)]
