"""Query rewriter: contextualizes the question from conversation history and
normalizes terminology (brand -> generic drug names, abbreviations) into one
standalone search query that feeds both retrieval legs.

Fails open: rewriting is an optimization, so a failed call falls back to the
raw query instead of blocking it.
"""

from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from prompts import QUERY_REWRITE
from retrieval.contract import HistoryMessage
from retrieval.query.transcript import build_user_prompt

QUERY_REWRITER_MODEL = "gpt-5-mini"


class QueryRewrite(BaseModel):
    rewritten_query: str


def build_rewrite_messages(
    query: str, history: list[HistoryMessage]
) -> list[ChatCompletionMessageParam]:
    return [
        {"role": "system", "content": QUERY_REWRITE},
        {"role": "user", "content": build_user_prompt(query, history)},
    ]


def choose_query(rewrite: QueryRewrite | None, raw_query: str) -> str:
    """The rewritten query when there is a usable one; the raw query otherwise."""
    if rewrite is None or not rewrite.rewritten_query:
        return raw_query
    return rewrite.rewritten_query


def run_query_rewriter(client: OpenAI, query: str, history: list[HistoryMessage]) -> str:
    """Adapter: fails open — a failed rewrite falls back to the raw query."""
    try:
        completion = client.chat.completions.parse(
            model=QUERY_REWRITER_MODEL,
            messages=build_rewrite_messages(query, history),
            response_format=QueryRewrite,
        )
    except OpenAIError:
        return query
    return choose_query(completion.choices[0].message.parsed, query)
