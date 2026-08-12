"""SSE encoding: one named frame per event, JSON payload, newlines in text kept intact."""

import json

from chat.context import Citation
from chat.events import DoneEvent, ErrorEvent, SourcesEvent, TokenEvent, encode_sse


def test_sources_frame_carries_the_tag_to_citation_mapping() -> None:
    citation = Citation(
        document_id="Warfarin_2",
        drug="warfarin",
        section_number="5.1",
        section_title="Hemorrhage",
        page_start=12,
    )
    frame = encode_sse(SourcesEvent(sources={"S1": citation}))
    assert frame.startswith("event: sources\ndata: ")
    assert frame.endswith("\n\n")
    assert json.loads(frame.splitlines()[1].removeprefix("data: ")) == {
        "sources": {
            "S1": {
                "document_id": "Warfarin_2",
                "drug": "warfarin",
                "section_number": "5.1",
                "section_title": "Hemorrhage",
                "page_start": 12,
            }
        }
    }


def test_sentinels_and_newlines_survive_token_encoding() -> None:
    frame = encode_sse(TokenEvent(text="risk [[S1]].\n\nMonitor INR"))
    lines = frame.splitlines()
    assert lines[0] == "event: token"
    # A raw newline in the answer would split one frame into two; JSON escaping stops it.
    assert len([line for line in lines if line.startswith("data: ")]) == 1
    assert json.loads(lines[1].removeprefix("data: ")) == {"text": "risk [[S1]].\n\nMonitor INR"}


def test_done_frame_defaults_its_annotation_to_null() -> None:
    frame = encode_sse(DoneEvent())
    assert frame.startswith("event: done\n")
    assert json.loads(frame.splitlines()[1].removeprefix("data: ")) == {"judge_grounded": None}


def test_error_frame_names_the_error_event() -> None:
    frame = encode_sse(ErrorEvent(message="broke"))
    assert frame.startswith("event: error\n")
    assert json.loads(frame.splitlines()[1].removeprefix("data: ")) == {"message": "broke"}
