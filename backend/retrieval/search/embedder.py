"""Embedder: the one configured embeddings client in this app.

Ingestion embeds every chunk with it and retrieval embeds every query with it, so both
sides use the model and width named in `config` — a stored vector and a query vector are
only comparable when they agree. Callers use the returned client's own
`embed_documents` / `embed_query`; wrapping those would add nothing.
"""

from langchain_openai import OpenAIEmbeddings

from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


def build_embeddings() -> OpenAIEmbeddings:
    """`text-embedding-3-large` truncated to 1536 dims, per `config`. The API key comes
    from the environment, the way `langchain-openai` reads it by default."""
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS)
