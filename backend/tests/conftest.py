"""Fixtures shared across the test suite."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from openai import OpenAIError

from chat.contract import RetrievedChunk
from persistence.rows import ChunkRow, DocumentRow


@pytest.fixture
def make_chunk() -> Callable[..., ChunkRow]:
    """Build a minimal valid chunk row. Ranking tests care only about identity, so
    everything except the id is filler; tests that read a chunk's location or text
    override those fields."""

    def build(
        chunk_id: int,
        document_id: str = "warfarin_1",
        content: str | None = None,
        section_number: str | None = "5",
        section_title: str | None = "WARNINGS AND PRECAUTIONS",
        page_start: int = 1,
    ) -> ChunkRow:
        return ChunkRow(
            id=chunk_id,
            document_id=document_id,
            content=content if content is not None else f"chunk {chunk_id}",
            content_sha256=f"{chunk_id:064x}",
            section_number=section_number,
            section_title=section_title,
            page_start=page_start,
            page_end=page_start,
            chunk_index=chunk_id,
            chunk_type="text",
        )

    return build


@pytest.fixture
def make_document() -> Callable[..., DocumentRow]:
    """Build a minimal valid document row; tests care about its id and drug name."""

    def build(document_id: str = "Warfarin_2", drug: str = "warfarin") -> DocumentRow:
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

    return build


@pytest.fixture
def make_retrieved(
    make_chunk: Callable[..., ChunkRow], make_document: Callable[..., DocumentRow]
) -> Callable[[], RetrievedChunk]:
    """One retrieved chunk with its parent document, the shape generation reads."""

    def build() -> RetrievedChunk:
        chunk = make_chunk(
            1,
            document_id="Warfarin_2",
            content="Bleeding risk is increased.",
            section_number="5.1",
            section_title="Hemorrhage",
            page_start=12,
        )
        return RetrievedChunk(chunk=chunk, document=make_document())

    return build


@pytest.fixture
def streaming_model() -> Callable[..., BaseChatModel]:
    """A model that yields the given deltas. Only `astream` is reached from chat/."""

    def build(*deltas: str) -> BaseChatModel:
        class Model:
            async def astream(
                self, *args: object, **kwargs: object
            ) -> AsyncIterator[AIMessageChunk]:
                for delta in deltas:
                    yield AIMessageChunk(content=delta)

        return cast(BaseChatModel, Model())

    return build


@pytest.fixture
def failing_model() -> Callable[..., BaseChatModel]:
    """A model that streams the given text, then loses the connection."""

    def build(partial: str) -> BaseChatModel:
        class Model:
            async def astream(
                self, *args: object, **kwargs: object
            ) -> AsyncIterator[AIMessageChunk]:
                yield AIMessageChunk(content=partial)
                raise OpenAIError("connection lost")

        return cast(BaseChatModel, Model())

    return build
