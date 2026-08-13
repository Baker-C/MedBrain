"""The two retrieval configurations the harness compares: baseline and everything on.

Dense search is the spine and runs in both; the suite measures what the sparse leg
and the reranker add together — the stretch goal's graded before/after. The gate and
rewriter stay on throughout: the advice cases need the gate, and on a single-turn
suite the rewrite toggle would measure only normalization, not worth doubling the run.

The two single-leg middle configurations were dropped. They doubled the run for an
attribution question the suite is too small to answer: on 13 scored cases a one-case
swing moves Recall@5 by 0.08, which is larger than the gap the middle columns exist to
show, so their numbers invited conclusions the sample size cannot support.
"""

from retrieval.config import RetrievalConfig

EVAL_CONFIGS: dict[str, RetrievalConfig] = {
    "dense": RetrievalConfig(sparse=False, rerank=False),
    "dense+sparse+rerank": RetrievalConfig(sparse=True, rerank=True),
}
