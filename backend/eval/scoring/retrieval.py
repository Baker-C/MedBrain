"""Rank metrics against a case's expected sources: Recall@K, MRR, Precision@K.

Each metric runs under two lenses. Strictness picks the document test — `strict`
requires the exact `document_id`, `lenient` accepts any sibling label of the same
drug. Granularity picks whether the section must also match. The lenient/strict gap
is reported rather than hidden: on this corpus a different-but-equally-correct
sibling label is not a retrieval failure, and only the strict lens can say whether
same-drug siblings are told apart.

Callers score only cases with expected sources; unanswerable and advice cases are
checked behaviorally instead (`eval.scoring.behavior`).
"""

from collections.abc import Sequence
from typing import Literal

from eval.cases import ExpectedSource
from eval.trace import ChunkTrace

Strictness = Literal["strict", "lenient"]
Granularity = Literal["document", "section"]


def is_hit(
    chunk: ChunkTrace,
    expected: ExpectedSource,
    strictness: Strictness,
    granularity: Granularity,
) -> bool:
    """Whether this chunk counts as a hit on this expected source under the lens."""
    document_ok = (
        chunk.document_id == expected.document_id
        if strictness == "strict"
        else chunk.drug == expected.drug
    )
    if not document_ok:
        return False
    if granularity == "document" or expected.section_number is None:
        return True
    return chunk.section_number == expected.section_number


def matches_any(
    chunk: ChunkTrace,
    expected: Sequence[ExpectedSource],
    strictness: Strictness,
    granularity: Granularity,
) -> bool:
    return any(is_hit(chunk, source, strictness, granularity) for source in expected)


def recall_at_k(
    chunks: Sequence[ChunkTrace],
    expected: Sequence[ExpectedSource],
    k: int,
    strictness: Strictness,
    granularity: Granularity,
) -> float:
    """The fraction of expected sources that some top-k chunk hits."""
    found = sum(
        1
        for source in expected
        if any(is_hit(chunk, source, strictness, granularity) for chunk in chunks[:k])
    )
    return found / len(expected)


def reciprocal_rank(
    chunks: Sequence[ChunkTrace],
    expected: Sequence[ExpectedSource],
    strictness: Strictness,
    granularity: Granularity,
) -> float:
    """1/rank of the first chunk hitting any expected source; 0.0 when none does.
    The suite's MRR is the mean of these."""
    for rank, chunk in enumerate(chunks, start=1):
        if matches_any(chunk, expected, strictness, granularity):
            return 1 / rank
    return 0.0


def precision_at_k(
    chunks: Sequence[ChunkTrace],
    expected: Sequence[ExpectedSource],
    k: int,
    strictness: Strictness,
    granularity: Granularity,
) -> float:
    """The fraction of the served top-k that hits some expected source.

    Divides by how many chunks were actually served (at most k), so a short result
    list is not penalized for being short; no chunks at all scores 0.0.
    """
    served = chunks[:k]
    if not served:
        return 0.0
    matching = sum(1 for chunk in served if matches_any(chunk, expected, strictness, granularity))
    return matching / len(served)
