"""Composes the retrieval stages into a configurable query path; config is an explicit
input.

The stages know nothing about each other or about the toggles. Every decision about what
runs, in what order, and how much survives each step is made here.
"""

from dataclasses import dataclass

import psycopg
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI
from psycopg.rows import TupleRow

from persistence.rows import ChunkRow
from retrieval.config import RetrievalConfig
from retrieval.contract import HistoryMessage, Refusal, Retrieved, ScoredChunk
from retrieval.query.query_gate import run_query_gate
from retrieval.query.query_rewriter import run_query_rewriter
from retrieval.ranking.fusion import fuse_rankings
from retrieval.ranking.reranker import RerankerModel, run_reranker
from retrieval.search.dense import run_dense_search
from retrieval.search.sparse import run_sparse_search


@dataclass(frozen=True)
class Proceed:
    """The query survived the gate; `query` is what the search legs will use. Internal to
    this module — callers see `Refusal | Retrieved`."""

    query: str


def prepare_query(
    client: OpenAI, query: str, history: list[HistoryMessage], config: RetrievalConfig
) -> Refusal | Proceed:
    """Gate, then rewrite. Each tool is toggleable; a refusal stops the pipeline,
    and with both toggles off the raw query proceeds without any LLM call."""
    if config.gate:
        refusal = run_query_gate(client, query, history)
        if refusal is not None:
            return refusal
    if config.rewrite:
        return Proceed(query=run_query_rewriter(client, query, history))
    return Proceed(query=query)


def sparse_candidates(
    conn: psycopg.Connection[TupleRow], query: str, config: RetrievalConfig
) -> list[ChunkRow]:
    """The keyword leg's candidates, or nothing when it is toggled off."""
    if not config.sparse:
        return []
    return run_sparse_search(conn, query, config.candidate_limit)


def retrieve_chunks(
    embeddings: OpenAIEmbeddings,
    reranker: RerankerModel,
    conn: psycopg.Connection[TupleRow],
    query: str,
    config: RetrievalConfig,
) -> list[ScoredChunk]:
    """Dense candidates always, plus the keyword leg's when it is on, fused on rank,
    optionally reranked, cut to the generation budget.

    With `sparse` off the fusion is a passthrough — reciprocal rank decreases with rank,
    so one list against an empty one keeps its own order — and the reranker simply sees
    the dense candidates instead of the union of both legs.
    """
    dense = run_dense_search(conn, embeddings.embed_query(query), config.candidate_limit)
    fused = fuse_rankings(
        dense,
        sparse_candidates(conn, query, config),
        rrf_k=config.rrf_k,
        limit=config.fused_limit,
    )
    ranked = run_reranker(reranker, query, fused) if config.rerank else fused
    # Relevance threshold drops in here: filter `ranked` on rerank_score (or on
    # rrf_score when the reranker is off) before the final cut, and an empty result
    # becomes the app's decline-to-answer path. Deliberately not built — see DESIGN.md.
    return ranked[: config.final_limit]


def run_retrieval(
    client: OpenAI,
    embeddings: OpenAIEmbeddings,
    reranker: RerankerModel,
    conn: psycopg.Connection[TupleRow],
    query: str,
    history: list[HistoryMessage],
    config: RetrievalConfig,
) -> Refusal | Retrieved:
    """The whole query path: gate, rewrite, search, fuse, rerank. Callers handle two
    outcomes — a refusal to stream as-is, or chunks to answer from.

    Each model client is passed in, built by its own stage's factory, because each tool
    picks its own model. `client` is the raw OpenAI SDK the gate and rewriter still use;
    it disappears when those two move onto `ChatOpenAI` (see DESIGN.md's debt list).
    """
    prepared = prepare_query(client, query, history, config)
    if isinstance(prepared, Refusal):
        return prepared
    return Retrieved(
        query=prepared.query,
        chunks=retrieve_chunks(embeddings, reranker, conn, prepared.query, config),
    )
