"""Composes retrieval tools into a configurable query path; config is an explicit input."""

from dataclasses import dataclass

from openai import OpenAI

from retrieval.config import RetrievalConfig
from retrieval.contract import HistoryMessage, Refusal
from retrieval.query.advice_gate import run_advice_gate
from retrieval.query.query_rewriter import run_query_rewriter


@dataclass(frozen=True)
class Proceed:
    query: str


def prepare_query(
    client: OpenAI, query: str, history: list[HistoryMessage], config: RetrievalConfig
) -> Refusal | Proceed:
    """Gate, then rewrite. Each tool is toggleable; a refusal stops the pipeline,
    and with both toggles off the raw query proceeds without any LLM call."""
    if config.gate:
        refusal = run_advice_gate(client, query, history)
        if refusal is not None:
            return refusal
    if config.rewrite:
        return Proceed(query=run_query_rewriter(client, query, history))
    return Proceed(query=query)
