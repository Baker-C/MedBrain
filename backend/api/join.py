"""The bridge between retrieval and context assembly: scored chunks plus their documents.

Pure logic, no I/O — the caller fetches the documents and hands them in.
"""

from chat.context import RetrievedChunk
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
