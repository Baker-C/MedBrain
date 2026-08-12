"""Adapter: the `documents` registry and the `chunks` table.

The schema is owned by the backend (`backend/persistence/migrations/`, applied with
`python -m persistence.migrate`); this job assumes it exists and writes rows into it.
Every row read back is validated into a model, so schema drift surfaces here as a
typed error instead of a wrong value further downstream.

A document's chunk changes and its registry row commit in one transaction, so a crash
cannot leave a document half-ingested.
"""

from collections.abc import Sequence

import psycopg
from psycopg.rows import TupleRow
from pydantic import BaseModel

from identity import DocumentIdentity
from models import ChunkLocation
from reconciliation import BucketDocument, ChunkPlan

UPSERT_DOCUMENT = """
insert into documents (id, storage_object_key, file_sha256, drug_name, manufacturer,
                       formulation, chunk_count, ingested_at)
values (%s, %s, %s, %s, %s, %s, %s, now())
on conflict (id) do update set
    storage_object_key = excluded.storage_object_key,
    file_sha256        = excluded.file_sha256,
    drug_name          = excluded.drug_name,
    manufacturer       = excluded.manufacturer,
    formulation        = excluded.formulation,
    chunk_count        = excluded.chunk_count,
    ingested_at        = excluded.ingested_at
"""

INSERT_CHUNK = """
insert into chunks (document_id, content, content_sha256, embedding, section_number,
                    section_title, page_start, page_end, chunk_index, chunk_type)
values (%s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s)
"""

RELOCATE_CHUNK = """
update chunks
   set section_number = %s, section_title = %s, page_start = %s, page_end = %s,
       chunk_index = %s
 where document_id = %s and content_sha256 = %s
"""

DELETE_CHUNKS = "delete from chunks where document_id = %s and content_sha256 = any(%s)"
DELETE_DOCUMENT = "delete from documents where id = %s"
SELECT_REGISTRY = "select id, file_sha256 from documents"
SELECT_CHUNK_LOCATIONS = """
select content_sha256, section_number, section_title, page_start, page_end, chunk_index
  from chunks where document_id = %s
"""


class RegistryEntry(BaseModel):
    id: str
    file_sha256: str


class StoredChunk(BaseModel):
    content_sha256: str
    section_number: str | None
    section_title: str | None
    page_start: int
    page_end: int
    chunk_index: int


def connect(database_url: str) -> psycopg.Connection[TupleRow]:
    return psycopg.connect(database_url)


def vector_literal(values: Sequence[float]) -> str:
    """pgvector's text input; the `::vector` cast in the statement does the conversion."""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def read_registry(connection: psycopg.Connection[TupleRow]) -> dict[str, str]:
    """Every ingested document's raw-file hash, keyed by document id."""
    with connection.cursor() as cursor:
        cursor.execute(SELECT_REGISTRY)
        rows = cursor.fetchall()
    entries = [RegistryEntry(id=row[0], file_sha256=row[1]) for row in rows]
    return {entry.id: entry.file_sha256 for entry in entries}


def read_chunk_locations(
    connection: psycopg.Connection[TupleRow], document_id: str
) -> dict[str, ChunkLocation]:
    with connection.cursor() as cursor:
        cursor.execute(SELECT_CHUNK_LOCATIONS, (document_id,))
        rows = cursor.fetchall()
    stored = [
        StoredChunk(
            content_sha256=row[0],
            section_number=row[1],
            section_title=row[2],
            page_start=row[3],
            page_end=row[4],
            chunk_index=row[5],
        )
        for row in rows
    ]
    return {
        chunk.content_sha256: ChunkLocation(
            section_number=chunk.section_number,
            section_title=chunk.section_title,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            chunk_index=chunk.chunk_index,
        )
        for chunk in stored
    }


def apply_document(
    connection: psycopg.Connection[TupleRow],
    document: BucketDocument,
    identity: DocumentIdentity,
    plan: ChunkPlan,
    embeddings: Sequence[Sequence[float]],
    chunk_count: int,
) -> None:
    """Commit one document's registry row and all of its chunk changes together."""
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            UPSERT_DOCUMENT,
            (
                document.document_id,
                document.object_key,
                document.file_sha256,
                identity.drug_name,
                identity.manufacturer,
                identity.formulation,
                chunk_count,
            ),
        )
        if plan.delete:
            cursor.execute(DELETE_CHUNKS, (document.document_id, list(plan.delete)))
        for chunk in plan.relocate:
            cursor.execute(
                RELOCATE_CHUNK,
                (
                    chunk.section_number,
                    chunk.section_title,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.chunk_index,
                    document.document_id,
                    chunk.content_sha256,
                ),
            )
        for chunk, embedding in zip(plan.insert, embeddings, strict=True):
            cursor.execute(
                INSERT_CHUNK,
                (
                    document.document_id,
                    chunk.content,
                    chunk.content_sha256,
                    vector_literal(embedding),
                    chunk.section_number,
                    chunk.section_title,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.chunk_index,
                    chunk.chunk_type,
                ),
            )


def delete_document(connection: psycopg.Connection[TupleRow], document_id: str) -> None:
    """Drop a document that left the bucket; its chunks cascade with it."""
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(DELETE_DOCUMENT, (document_id,))
