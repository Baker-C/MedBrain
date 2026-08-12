"""Typed application settings, read from the environment (or a local .env file)."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Fixed, not environment-tunable: ingestion and retrieval must embed with the same
# model at the same width or their vectors are not comparable, and the width is
# already frozen into the schema as vector(1536) (see 0001_initial_schema.sql).
# text-embedding-3-large is truncated from its native 3072 dims via the API's
# `dimensions` parameter because pgvector's HNSW index caps at 2000.
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    supabase_url: str
    supabase_service_key: str
    database_url: str
    openai_api_key: str
    frontend_origin: str = "http://localhost:5173"


def load_settings() -> Settings:
    """Build Settings from the environment; the values mypy wants as arguments come from there."""
    return Settings()  # type: ignore[call-arg]
