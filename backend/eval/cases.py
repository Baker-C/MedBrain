"""The suite's vocabulary: one authored question and what a correct run looks like.

A case names each expected source at two strictnesses at once: `document_id` is the
strict lens (the exact label the case was authored against) and `drug` the lenient
one (any sibling label of the same drug counts). Six of the ten drugs have
near-identical sibling labels, so the two lenses genuinely differ; the harness
reports both and the gap between them.
"""

from typing import Literal

from pydantic import BaseModel

CaseKind = Literal["lookup", "table", "synthesis", "discrimination", "unanswerable", "advice"]


class ExpectedSource(BaseModel):
    """One place a correct answer comes from. `section_number` is None when any
    section of the document is acceptable; document-granularity metrics ignore it
    either way."""

    document_id: str
    drug: str
    section_number: str | None = None


class EvalCase(BaseModel):
    """One authored question with its ground truth.

    `expected` is empty for unanswerable and advice cases — nothing in the corpus
    should ground them, so they are scored behaviorally rather than by rank metrics.
    `forbidden_drugs` names the look-alikes a discrimination trap must not retrieve.
    `expected_answer` is what the judge compares against — for the cases that must
    decline, the canned refusal text itself.
    """

    id: str
    question: str
    kind: CaseKind
    expected_answer: str
    expected: list[ExpectedSource] = []
    forbidden_drugs: list[str] = []
