"""History rendering: the transcript appears only when there is history."""

from retrieval.contract import HistoryMessage
from retrieval.query.transcript import build_user_prompt


def test_user_prompt_includes_history_transcript() -> None:
    history = [
        HistoryMessage(role="user", content="What does the warfarin label say on bleeding?"),
        HistoryMessage(role="assistant", content="Section 5.1 covers hemorrhage risk."),
    ]
    prompt = build_user_prompt("What about dosing?", history)
    assert "user: What does the warfarin label say on bleeding?" in prompt
    assert "assistant: Section 5.1 covers hemorrhage risk." in prompt
    assert "Latest question: What about dosing?" in prompt


def test_user_prompt_without_history_is_just_the_question() -> None:
    assert build_user_prompt("Standalone question?", []) == "Latest question: Standalone question?"
