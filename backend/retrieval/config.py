"""Retrieval configuration: every switch and cut-off the query path obeys.

One object, passed in explicitly rather than read from ambient state, so the eval
harness can run the same questions under several configurations in one session and
the query endpoint can map its request parameters onto a single shape.

Dense vector search is the spine and always runs — it is the retrieval this app would
have with no stretch goal at all. Everything else is a switch layered on top, which is
what makes the eval deltas readable: dense alone, dense plus the keyword leg, then the
same again with reranking.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalConfig:
    """Defaults are what in-app traffic runs; the eval harness varies one field at a time."""

    gate: bool = True
    rewrite: bool = True
    sparse: bool = True  # add the keyword leg's candidates to the dense ones
    rerank: bool = True
    candidate_limit: int = 40  # per search leg, before fusion
    rrf_k: int = 60  # RRF damping: large enough that no single leg's top hit dominates
    fused_limit: int = 20  # candidates handed to the reranker
    final_limit: int = 8  # chunks handed to generation
