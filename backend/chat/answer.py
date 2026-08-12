"""Where the chat layer comes together: retrieved chunks in, an ordered event stream out.

Two entry points over one path. `stream_answer_events` is what the SSE endpoint
serves; `trace_answer` collects the same events into a single payload for the eval
harness, so the harness measures the path users actually get rather than a parallel one.
"""

from collections.abc import AsyncIterator, Sequence

from langchain_core.language_models import BaseChatModel
from openai import OpenAIError
from pydantic import BaseModel

from chat.context import Citation, RetrievedChunk, build_context, build_sources, emitted_tags
from chat.events import DoneEvent, ErrorEvent, QueryEvent, SourcesEvent, TokenEvent
from chat.generation import stream_answer
from messages import ANSWER_UNAVAILABLE, NO_SUPPORTING_CONTEXT


class AnswerTrace(BaseModel):
    """One full answer with its citations, for the eval harness.

    `tags` are the sentinels the answer really emitted, which the harness checks against
    `sources` to confirm every citation resolves to a chunk that was actually retrieved.
    """

    answer: str
    sources: dict[str, Citation]
    tags: list[str]
    error: str | None = None


async def stream_canned_events(text: str) -> AsyncIterator[QueryEvent]:
    """A pre-written answer as a well-formed stream: empty mapping, one token, done.

    Shared by the no-context path here and by a gate refusal upstream, so a canned
    response reaches the client through the same contract as a generated one.
    """
    yield SourcesEvent(sources={})
    yield TokenEvent(text=text)
    yield DoneEvent()


async def stream_answer_events(
    model: BaseChatModel, question: str, chunks: Sequence[RetrievedChunk]
) -> AsyncIterator[QueryEvent]:
    """The mapping first, then answer tokens, then done -- or error if generation fails.

    With no chunks there is nothing to be grounded in, so the canned message goes out
    and no generation call is made.
    """
    if not chunks:
        async for event in stream_canned_events(NO_SUPPORTING_CONTEXT):
            yield event
        return

    yield SourcesEvent(sources=build_sources(chunks))
    try:
        async for text in stream_answer(model, question, build_context(chunks)):
            yield TokenEvent(text=text)
    except OpenAIError:
        # Mid-stream failure: the client has already rendered part of an answer, so it
        # gets an error event rather than a silent truncation.
        yield ErrorEvent(message=ANSWER_UNAVAILABLE)
        return
    yield DoneEvent()


async def trace_answer(
    model: BaseChatModel, question: str, chunks: Sequence[RetrievedChunk]
) -> AnswerTrace:
    """The same event stream, collected into one payload instead of served as SSE."""
    parts: list[str] = []
    sources: dict[str, Citation] = {}
    error: str | None = None
    async for event in stream_answer_events(model, question, chunks):
        match event:
            case SourcesEvent():
                sources = event.sources
            case TokenEvent():
                parts.append(event.text)
            case ErrorEvent():
                error = event.message
            case DoneEvent():
                pass
    answer = "".join(parts)
    return AnswerTrace(answer=answer, sources=sources, tags=emitted_tags(answer), error=error)
