"""Adapter: embeddings, capped to the width pgvector can index.

`text-embedding-3-large` emits 3072 dimensions natively, but pgvector's HNSW index
stops at 2000 — a 3072-wide column is storable and then sequentially scanned on every
query. The model is Matryoshka-trained, so asking for its leading 1536 dimensions
keeps the stronger model and keeps the index.

The client is `langchain-openai`'s `OpenAIEmbeddings`, which is the embeddings client
for ingestion and for query embedding alike — one client library for every OpenAI call,
with no per-call-type exception to remember.
"""

from collections.abc import Sequence

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from errors import IngestionError

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536


def build_embeddings(api_key: str) -> OpenAIEmbeddings:
    """Built by its caller, so the credential stays an explicit input."""
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
        api_key=SecretStr(api_key),
    )


def embed_texts(embeddings: Embeddings, texts: Sequence[str]) -> list[list[float]]:
    """Embed in input order. Batching is the client's business; the pairing is ours.

    Vectors are zipped with their chunks at insert time, so a response that came back
    short would attach the wrong embedding to a chunk rather than fail.
    """
    if not texts:
        return []
    vectors = embeddings.embed_documents(list(texts))
    if len(vectors) != len(texts):
        raise IngestionError(f"Embedded {len(vectors)} of {len(texts)} chunks.")
    return vectors
