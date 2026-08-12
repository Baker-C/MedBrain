"""Typed row models: one per table, carrying only the columns the app reads.

Adapters validate every row they read into these models, so schema drift surfaces
as a typed validation error at the boundary. `chunks.embedding` and `chunks.tsv`
are deliberately absent — no code path reads them back.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, JsonValue


class DocumentRow(BaseModel):
    id: str
    storage_object_key: str
    file_sha256: str
    drug_name: str
    manufacturer: str
    formulation: str | None
    chunk_count: int
    ingested_at: datetime


class ChunkRow(BaseModel):
    id: int
    document_id: str
    content: str
    content_sha256: str
    section_number: str | None
    section_title: str | None
    page_start: int
    page_end: int
    chunk_index: int
    chunk_type: Literal["text", "table"]


class ConversationRow(BaseModel):
    id: UUID
    title: str
    created_at: datetime


class MessageRow(BaseModel):
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    # Write-once tag→citation snapshot, read whole; its inner shape is owned by
    # the streaming contract and typed there once that exists.
    sources: dict[str, JsonValue] | None
    created_at: datetime
