"""Context assembly: retrieved chunks in, per-query sentinel tags and citations out.

Pure logic, no I/O. Tags (`S1`, `S2`, ...) are positional and per-query — they are
never stored on a chunk. Both the citation mapping and the prompt context derive
their tags from the same position, so the two cannot disagree.

A citation is a join: identity (document id, drug) comes from the document, location
(section, page) from the chunk.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from persistence.rows import ChunkRow

TAG_PATTERN = re.compile(r"\[\[(S\d+)\]\]")


class CitedDocument(Protocol):
    """The document fields a citation needs. `DocumentRow` satisfies this structurally,
    so `chat/` sees only these two and a rename in the row model fails the type check."""

    id: str
    drug_name: str


@dataclass(frozen=True)
class RetrievedChunk:
    """One chunk retrieval selected, with the document it belongs to.

    An in-process handoff of rows already validated at the retrieval adapter, so it is
    a dataclass rather than a model — the same shape `Refusal` and `Proceed` use.
    """

    chunk: ChunkRow
    document: CitedDocument


class Citation(BaseModel):
    """One resolved source, sent in the `sources` event and frozen into `messages.sources`.

    Section fields degrade to null on a chunk with no carved section; `page_start` is
    the guaranteed floor every citation deep-links to.
    """

    document_id: str
    drug: str
    section_number: str | None
    section_title: str | None
    page_start: int


def tag_for(position: int) -> str:
    """The sentinel tag of the chunk at this position in the retrieved set."""
    return f"S{position + 1}"


def sentinel(tag: str) -> str:
    """The tag as it appears in prompt text and in the model's answer."""
    return f"[[{tag}]]"


def section_label(chunk: ChunkRow) -> str | None:
    """`5.1 Hemorrhage` when the chunk carries a carved section; None when it does not."""
    parts = [part for part in (chunk.section_number, chunk.section_title) if part]
    return " ".join(parts) if parts else None


def citation_for(retrieved: RetrievedChunk) -> Citation:
    return Citation(
        document_id=retrieved.document.id,
        drug=retrieved.document.drug_name,
        section_number=retrieved.chunk.section_number,
        section_title=retrieved.chunk.section_title,
        page_start=retrieved.chunk.page_start,
    )


def build_sources(chunks: Sequence[RetrievedChunk]) -> dict[str, Citation]:
    """The tag→citation mapping the client resolves sentinels against."""
    return {tag_for(position): citation_for(chunk) for position, chunk in enumerate(chunks)}


def context_block(tag: str, retrieved: RetrievedChunk) -> str:
    """One tagged excerpt: its sentinel, where it came from, then the text itself.

    The heading names the drug so the model can tell near-identical sibling labels apart.
    """
    heading = " - ".join(
        part for part in (retrieved.document.drug_name, section_label(retrieved.chunk)) if part
    )
    return f"{sentinel(tag)} {heading}\n{retrieved.chunk.content}"


def build_context(chunks: Sequence[RetrievedChunk]) -> str:
    """Every retrieved chunk as tagged excerpts, in retrieved order."""
    return "\n\n".join(
        context_block(tag_for(position), chunk) for position, chunk in enumerate(chunks)
    )


def emitted_tags(answer: str) -> list[str]:
    """The sentinel tags the answer actually cited, in order of first appearance.

    The eval harness checks each one resolves to a chunk that was really retrieved.
    """
    seen = dict.fromkeys(TAG_PATTERN.findall(answer))
    return list(seen)
