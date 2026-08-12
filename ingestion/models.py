"""The typed values ingestion stages hand to each other.

`PageElement` is the seam between the single impure extraction adapter and every pure
stage after it: nothing downstream of `extraction.py` knows that Unstructured exists,
which is what lets carving, splitting, and stamping be tested without a PDF.
"""

from dataclasses import dataclass
from typing import Literal

ElementKind = Literal["title", "text", "table"]
ChunkType = Literal["text", "table"]


@dataclass(frozen=True)
class PageElement:
    """One extracted block of a PDF, already reduced to what ingestion needs.

    Carries a page span rather than a single page: extraction sets both ends to the
    same page, and stitching a table across a page boundary widens it. Page is the
    citation floor, so it is tracked on the element rather than reconstructed later.
    """

    kind: ElementKind
    text: str
    page_start: int
    page_end: int
    html: str | None = None


@dataclass(frozen=True)
class Section:
    """A carved section of a label: its heading, and the elements underneath it.

    `number` and `title` are nullable because real labels carry unnumbered sections —
    every boxed warning in the corpus is one.
    """

    number: str | None
    title: str | None
    elements: tuple[PageElement, ...]


@dataclass(frozen=True)
class DraftChunk:
    """A chunk after splitting, before it is stamped with its hash and index."""

    content: str
    section_number: str | None
    section_title: str | None
    page_start: int
    page_end: int
    chunk_type: ChunkType


@dataclass(frozen=True)
class Chunk:
    """A stamped chunk, ready to embed and insert."""

    content: str
    content_sha256: str
    section_number: str | None
    section_title: str | None
    page_start: int
    page_end: int
    chunk_index: int
    chunk_type: ChunkType


@dataclass(frozen=True)
class ChunkLocation:
    """Where a stored chunk sits in its document — the part a revision can move."""

    section_number: str | None
    section_title: str | None
    page_start: int
    page_end: int
    chunk_index: int


def location_of(chunk: Chunk) -> ChunkLocation:
    return ChunkLocation(
        section_number=chunk.section_number,
        section_title=chunk.section_title,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        chunk_index=chunk.chunk_index,
    )
