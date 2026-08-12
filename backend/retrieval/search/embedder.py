"""Embedder: the one configured embeddings client in this app.

Ingestion embeds every chunk with it and retrieval embeds every query with it, so both
sides use the model and width named in `config` — a stored vector and a query vector are
only comparable when they agree. Callers use the returned client's own
`embed_documents` / `embed_query`; wrapping those would add nothing.
"""

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


def build_embeddings(api_key: str) -> OpenAIEmbeddings:
    """`text-embedding-3-large` truncated to 1536 dims, per `config`. Built by its caller
    so the credential stays an explicit input."""
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS, api_key=SecretStr(api_key)
    )
