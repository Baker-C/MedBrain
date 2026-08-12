"""Retrieved chunks in, an ordered event stream out.

The only place events are produced. Both kinds of answer this app gives — a canned
one and a generated one — leave here as the same well-formed stream, so nothing
downstream has to know which it is handling.
"""

from collections.abc import AsyncIterator, Sequence

from langchain_core.language_models import BaseChatModel
from openai import OpenAIError

from chat.context import build_context, build_sources
from chat.contract import (
    DoneEvent,
    ErrorEvent,
    QueryEvent,
    RetrievedChunk,
    SourcesEvent,
    TokenEvent,
)
from chat.generation import stream_answer
from messages import ANSWER_UNAVAILABLE, NO_SUPPORTING_CONTEXT


async def stream_canned_events(text: str) -> AsyncIterator[QueryEvent]:
    """A pre-written answer as a well-formed stream: empty mapping, one token, done.

    Shared by the no-context path here and by a gate refusal upstream, so a canned
    response reaches the client through the same contract as a generated one — and
    folds back to the same shape, which is why the history write needs no special case.
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
