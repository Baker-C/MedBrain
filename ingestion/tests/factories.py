"""Builders, so a test reads as document structure rather than constructor noise."""

from models import Chunk, DraftChunk, PageElement


def text(body: str, page: int = 1, page_end: int | None = None) -> PageElement:
    return PageElement(kind="text", text=body, page_start=page, page_end=page_end or page)


def title(body: str, page: int = 1) -> PageElement:
    return PageElement(kind="title", text=body, page_start=page, page_end=page)


def table(html: str, page: int = 1, page_end: int | None = None, body: str = "") -> PageElement:
    return PageElement(
        kind="table", text=body, page_start=page, page_end=page_end or page, html=html
    )


def draft(content: str, page: int = 1, page_end: int | None = None) -> DraftChunk:
    return DraftChunk(
        content=content,
        section_number="5.1",
        section_title="Hemorrhage",
        page_start=page,
        page_end=page_end or page,
        chunk_type="text",
    )


def chunk(
    content_sha256: str,
    page: int = 1,
    chunk_index: int = 0,
    section_number: str | None = "5.1",
) -> Chunk:
    return Chunk(
        content="content",
        content_sha256=content_sha256,
        section_number=section_number,
        section_title="Hemorrhage",
        page_start=page,
        page_end=page,
        chunk_index=chunk_index,
        chunk_type="text",
    )
