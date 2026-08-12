"""The bridge between retrieval and context assembly: scored chunks plus their documents.

Retrieval returns chunks; a citation also needs the document each one came from. That
lookup is one query, and the pairing that follows is pure.
"""

import psycopg
from psycopg.rows import TupleRow

from chat.contract import RetrievedChunk
from persistence.documents import fetch_documents
from persistence.rows import DocumentRow
from retrieval.contract import ScoredChunk


def attach_documents(
    chunks: list[ScoredChunk], documents: dict[str, DocumentRow]
) -> list[RetrievedChunk]:
    """Pair each retrieved chunk with the document it came from, in retrieved order.

    A missing id raises `KeyError` on purpose: a chunk's parent is guaranteed by the
    foreign key, so its absence is corruption and must surface rather than be skipped.
    """
    return [
        RetrievedChunk(chunk=scored.chunk, document=documents[scored.chunk.document_id])
        for scored in chunks
    ]


def load_retrieved(
    conn: psycopg.Connection[TupleRow], chunks: list[ScoredChunk]
) -> list[RetrievedChunk]:
    """The chunk→document join: one query for the parent documents, then the pure pairing."""
    documents = fetch_documents(conn, {scored.chunk.document_id for scored in chunks})
    return attach_documents(chunks, documents)
