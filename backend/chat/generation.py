"""Grounded generation: the streaming model call.

A thin adapter. It owns the model choice and the message shape; everything it needs
about the retrieved chunks arrives as an assembled context string, so nothing here
knows what a chunk is.

The generation prompt sees the standalone question and the excerpts only -- never the
conversation history. Making a follow-up standalone is the query rewriter's job, and
leaving history out means no ungrounded prior turn competes with the labeling for the
model's attention.
"""

from collections.abc import AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from prompts import GROUNDED_ANSWER

GENERATION_MODEL = "gpt-5-mini"


def generation_model(api_key: str) -> ChatOpenAI:
    """The generation model, built by its caller so the credential stays an explicit input."""
    return ChatOpenAI(model=GENERATION_MODEL, api_key=SecretStr(api_key))


def build_answer_messages(question: str, context: str) -> list[BaseMessage]:
    return [
        SystemMessage(content=GROUNDED_ANSWER),
        HumanMessage(content=f"Labeling excerpts:\n{context}\n\nQuestion: {question}"),
    ]


async def stream_answer(model: BaseChatModel, question: str, context: str) -> AsyncIterator[str]:
    """Answer text as the model produces it. Empty deltas are dropped; nothing else is touched."""
    async for chunk in model.astream(build_answer_messages(question, context)):
        if chunk.text:
            yield chunk.text
