"""The four retrieval configurations the harness compares.

Dense search is the spine and runs in all of them; the suite measures what the
sparse leg and the reranker each add — the stretch goal's graded before/after. The
gate and rewriter stay on throughout: the advice cases need the gate, and on a
single-turn suite the rewrite toggle would measure only normalization, not worth
doubling the run.
"""

from retrieval.config import RetrievalConfig

EVAL_CONFIGS: dict[str, RetrievalConfig] = {
    "dense": RetrievalConfig(sparse=False, rerank=False),
    "dense+sparse": RetrievalConfig(sparse=True, rerank=False),
    "dense+rerank": RetrievalConfig(sparse=False, rerank=True),
    "dense+sparse+rerank": RetrievalConfig(sparse=True, rerank=True),
}
