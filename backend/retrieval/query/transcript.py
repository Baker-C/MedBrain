"""Rendering conversation history into a prompt, shared by both query-stage tools."""

from retrieval.contract import HistoryMessage


def build_user_prompt(query: str, history: list[HistoryMessage]) -> str:
    """The latest question, prefixed with a labeled transcript when history exists."""
    if not history:
        return f"Latest question: {query}"
    transcript = "\n".join(f"{message.role}: {message.content}" for message in history)
    return f"Conversation so far:\n{transcript}\n\nLatest question: {query}"
