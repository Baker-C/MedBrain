"""Embedder: the one client is built at the configured model and width."""

from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from retrieval.search.embedder import build_embeddings


def test_the_client_carries_the_configured_model_and_width() -> None:
    """The drift this guards against is silent: a query embedded at a different width or
    by a different model is not comparable to what ingestion stored."""
    embeddings = build_embeddings("not-a-real-key")
    assert embeddings.model == EMBEDDING_MODEL
    assert embeddings.dimensions == EMBEDDING_DIMENSIONS


def test_the_width_matches_the_schema() -> None:
    """`chunks.embedding` is `vector(1536)` in 0001_initial_schema.sql."""
    assert EMBEDDING_DIMENSIONS == 1536
