"""Typed ingestion settings, read from the environment (or a local .env file)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    supabase_url: str
    supabase_service_key: str
    database_url: str
    openai_api_key: str
    # Must match the bucket the upload script seeds (scripts/upload/upload_corpus.py).
    corpus_bucket: str = "corpus"


def load_settings() -> Settings:
    """Build Settings from the environment; the values mypy wants as arguments come from there."""
    return Settings()  # type: ignore[call-arg]
