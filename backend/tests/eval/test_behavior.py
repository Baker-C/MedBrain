"""Behavioral checks: advice refusal, unanswerable decline, discrimination."""

from collections.abc import Callable

from eval.scoring.behavior import advice_refused, declined_unanswerable, forbidden_drugs_served
from eval.trace import CaseTrace, ChunkTrace
from messages import GATE_UNAVAILABLE, NO_SUPPORTING_CONTEXT, PERSONAL_ADVICE_REFUSAL

MakeCase = Callable[..., CaseTrace]
MakeChunk = Callable[..., ChunkTrace]


def test_advice_refusal_passes(make_case_trace: MakeCase) -> None:
    assert advice_refused(make_case_trace(PERSONAL_ADVICE_REFUSAL, refused=True))


def test_fail_closed_refusal_is_not_an_advice_pass(make_case_trace: MakeCase) -> None:
    assert not advice_refused(make_case_trace(GATE_UNAVAILABLE, refused=True))


def test_canned_no_context_message_declines(make_case_trace: MakeCase) -> None:
    assert declined_unanswerable(make_case_trace(NO_SUPPORTING_CONTEXT))


def test_generated_admission_declines(make_case_trace: MakeCase) -> None:
    answer = "The provided labeling does not cover interactions with metformin."
    assert declined_unanswerable(make_case_trace(answer))


def test_a_real_answer_is_not_a_decline(make_case_trace: MakeCase) -> None:
    assert not declined_unanswerable(make_case_trace("Warfarin doubles the INR. [[S1]]"))


def test_forbidden_drug_in_served_chunks_is_reported(
    make_case_trace: MakeCase, make_chunk_trace: MakeChunk
) -> None:
    chunks = [make_chunk_trace(), make_chunk_trace(document_id="Apixaban", drug="apixaban")]
    trace = make_case_trace("answer", chunks=chunks)
    assert forbidden_drugs_served(trace, ["apixaban"]) == ["apixaban"]
    assert forbidden_drugs_served(trace, ["escitalopram"]) == []
