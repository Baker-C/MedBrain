"""The composition root: every shared client is built once at startup from explicit
settings, never read from ambient environment by the tool that uses it.

Each stage's factory still owns its own model choice; this module only supplies the
credential and holds the results together so a caller can reach them. It sits above
the feature packages and below the API, because the eval harness builds the same
clients without an app around them.
"""

from dataclasses import dataclass

import supabase
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import OpenAI
from supabase import Client

from chat.generation import generation_model
from config import Settings
from retrieval.ranking.reranker import RerankerModel, build_reranker
from retrieval.search.embedder import build_embeddings


@dataclass(frozen=True)
class AppClients:
    """The clients every request shares. `openai` is the raw SDK the advice gate and
    query rewriter still use; it goes away when those move onto `ChatOpenAI`."""

    settings: Settings
    generation: ChatOpenAI
    embeddings: OpenAIEmbeddings
    reranker: RerankerModel
    openai: OpenAI
    storage: Client


def build_clients(settings: Settings) -> AppClients:
    return AppClients(
        settings=settings,
        generation=generation_model(settings.openai_api_key),
        embeddings=build_embeddings(settings.openai_api_key),
        reranker=build_reranker(settings.openai_api_key),
        openai=OpenAI(api_key=settings.openai_api_key),
        storage=supabase.create_client(settings.supabase_url, settings.supabase_service_key),
    )
