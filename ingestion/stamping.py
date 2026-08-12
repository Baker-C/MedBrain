"""Stamp chunks with the identity that makes a re-run idempotent.

The chunk hash is content-only on purpose: the embedding model is fixed, so identical
text always yields the same vector and nothing about the model needs encoding here.
Location is deliberately outside the hash — a revised label that moves a paragraph to
a new page should refresh that chunk's citation, not re-embed it.
"""

import hashlib
from collections.abc import Sequence

from errors import IngestionError
from models import Chunk, DraftChunk


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def file_sha256(data: bytes) -> str:
    """Document-level idempotency key: the raw PDF bytes, so an unchanged file is skipped."""
    return hashlib.sha256(data).hexdigest()


def check_pages(draft: DraftChunk) -> None:
    if draft.page_start < 1 or draft.page_end < draft.page_start:
        raise IngestionError(
            f"Chunk has no usable page span ({draft.page_start}-{draft.page_end}) in section "
            f"{draft.section_number or draft.section_title or 'unknown'}; page is the citation "
            "floor and is never optional."
        )


def stamp_chunks(drafts: Sequence[DraftChunk]) -> list[Chunk]:
    """Hash and index each chunk, collapsing content that repeats inside one document.

    `UNIQUE (document_id, content_sha256)` is the reconciliation key, so a document
    cannot hold the same content twice; the second copy would be the same row.
    """
    stamped: list[Chunk] = []
    seen: set[str] = set()
    for draft in drafts:
        check_pages(draft)
        digest = content_sha256(draft.content)
        if digest in seen:
            continue
        seen.add(digest)
        stamped.append(
            Chunk(
                content=draft.content,
                content_sha256=digest,
                section_number=draft.section_number,
                section_title=draft.section_title,
                page_start=draft.page_start,
                page_end=draft.page_end,
                chunk_index=len(stamped),
                chunk_type=draft.chunk_type,
            )
        )
    return stamped
