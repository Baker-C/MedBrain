"""The ingestion spine: a bucket of PDFs in, chunks and registry rows out.

Run once, locally, in the ingestion container. It starts, reconciles the corpus into
the hosted database, prints what it did, and exits — no port, nothing served. It meets
the deployed backend only at Supabase: this job writes chunks and the registry, the
backend reads them and mints signed URLs against the same bucket.

    python -m pipeline
"""

from collections.abc import Sequence

import psycopg
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from psycopg.rows import TupleRow
from supabase import Client

from carving import body_elements, carve_sections
from cleaning import clean_elements
from config import Settings, load_settings
from embedding import build_embeddings, embed_texts
from errors import IngestionError
from extraction import extract_elements
from identity import build_identity_model, extract_identity
from models import Chunk, PageElement
from reconciliation import BucketDocument, ChunkPlan, document_id_for, plan_chunks, plan_corpus
from registry import apply_document, connect, delete_document, read_chunk_locations, read_registry
from splitting import split_sections
from stamping import file_sha256, stamp_chunks
from storage import download_object, list_corpus_objects, storage_client


def fingerprint_bucket(
    client: Client, bucket: str
) -> tuple[list[BucketDocument], dict[str, bytes]]:
    """Download every corpus PDF and hash it — the hash is what decides who gets extracted.

    Downloading all of them is cheap; `hi_res` extraction is not, and that is what an
    unchanged document skips.
    """
    documents: list[BucketDocument] = []
    payloads: dict[str, bytes] = {}
    for object_key in list_corpus_objects(client, bucket):
        data = download_object(client, bucket, object_key)
        document_id = document_id_for(object_key)
        documents.append(
            BucketDocument(
                document_id=document_id, object_key=object_key, file_sha256=file_sha256(data)
            )
        )
        payloads[document_id] = data
    return documents, payloads


def chunks_from_elements(elements: Sequence[PageElement]) -> list[Chunk]:
    """The whole pure half of ingestion: window, clean, carve, split, stamp."""
    return stamp_chunks(split_sections(carve_sections(clean_elements(body_elements(elements)))))


def ingest_document(
    connection: psycopg.Connection[TupleRow],
    model: BaseChatModel,
    embeddings: Embeddings,
    document: BucketDocument,
    pdf: bytes,
) -> ChunkPlan:
    elements = extract_elements(pdf)
    identity = extract_identity(model, document.document_id, elements)
    chunks = chunks_from_elements(elements)
    if not chunks:
        raise IngestionError(
            f"{document.document_id} produced no chunks; its structure does not match the "
            "PLR carving rules and it would be registered as an empty document."
        )

    plan = plan_chunks(chunks, read_chunk_locations(connection, document.document_id))
    vectors = embed_texts(embeddings, [chunk.content for chunk in plan.insert])
    apply_document(connection, document, identity, plan, vectors, len(chunks))
    return plan


def describe(document_id: str, plan: ChunkPlan) -> str:
    return (
        f"{document_id}: {len(plan.insert)} new, {len(plan.relocate)} moved, "
        f"{len(plan.delete)} orphaned, {len(plan.unchanged)} unchanged"
    )


def run(settings: Settings) -> None:
    client = storage_client(settings.supabase_url, settings.supabase_service_key)
    model = build_identity_model(settings.openai_api_key)
    embeddings = build_embeddings(settings.openai_api_key)

    # The database is opened before the corpus is downloaded: an unreachable database
    # should fail in the first second, not after pulling every PDF in the bucket.
    with connect(settings.database_url) as connection:
        registry = read_registry(connection)
        documents, payloads = fingerprint_bucket(client, settings.corpus_bucket)
        plan = plan_corpus(documents, registry)
        print(
            f"{len(documents)} documents in the bucket: {len(plan.ingest)} to ingest, "
            f"{len(plan.unchanged)} unchanged, {len(plan.removed)} removed"
        )
        for document_id in plan.removed:
            delete_document(connection, document_id)
            print(f"{document_id}: gone from the bucket, chunks deleted")
        for document in plan.ingest:
            chunk_plan = ingest_document(
                connection, model, embeddings, document, payloads[document.document_id]
            )
            print(describe(document.document_id, chunk_plan))


def main() -> None:
    run(load_settings())


if __name__ == "__main__":
    main()
