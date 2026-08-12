"""Folding a stream: a generated answer, a canned one, and a mid-stream failure.

The canned case matters most — it is why a refusal needs no special handling anywhere
downstream: it folds to the same shape a generated answer does.
"""

import asyncio
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel

from chat.collect import collect_answer
from chat.contract import RetrievedChunk
from chat.stream import stream_answer_events, stream_canned_events
from messages import ANSWER_UNAVAILABLE

MakeRetrieved = Callable[[], RetrievedChunk]
MakeModel = Callable[..., BaseChatModel]


def test_a_generated_answer_folds_into_its_text_tags_and_sources(
    streaming_model: MakeModel, make_retrieved: MakeRetrieved
) -> None:
    model = streaming_model("Bleeding risk ", "is increased [[S1]].")
    events = stream_answer_events(model, "warfarin bleeding risk", [make_retrieved()])
    answer = asyncio.run(collect_answer(events))

    assert answer.answer == "Bleeding risk is increased [[S1]]."
    assert answer.tags == ["S1"]
    assert list(answer.sources) == ["S1"]
    assert answer.error is None


def test_a_canned_answer_folds_to_its_text_and_an_empty_mapping() -> None:
    answer = asyncio.run(collect_answer(stream_canned_events("canned refusal")))

    assert answer.answer == "canned refusal"
    assert answer.sources == {}
    assert answer.tags == []
    assert answer.error is None


def test_a_mid_stream_failure_keeps_the_partial_text_and_records_the_error(
    failing_model: MakeModel, make_retrieved: MakeRetrieved
) -> None:
    model = failing_model("Warfarin raises bleeding risk [[S1]]")
    events = stream_answer_events(model, "warfarin bleeding risk", [make_retrieved()])
    answer = asyncio.run(collect_answer(events))

    assert answer.error == ANSWER_UNAVAILABLE
    assert answer.answer == "Warfarin raises bleeding risk [[S1]]"
