"""Conversation history: the shared message shape and its rendering into a prompt."""

from typing import Literal

from pydantic import BaseModel


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


def build_user_prompt(query: str, history: list[HistoryMessage]) -> str:
    """The latest question, prefixed with a labeled transcript when history exists."""
    if not history:
        return f"Latest question: {query}"
    transcript = "\n".join(f"{message.role}: {message.content}" for message in history)
    return f"Conversation so far:\n{transcript}\n\nLatest question: {query}"
