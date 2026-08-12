"""Prompt texts, one per module; import them from this package index."""

from prompts.advice_gate import ADVICE_GATE
from prompts.eval_judge import EVAL_JUDGE
from prompts.grounded_answer import GROUNDED_ANSWER
from prompts.query_rewrite import QUERY_REWRITE
from prompts.rerank import RERANK

__all__ = ["ADVICE_GATE", "EVAL_JUDGE", "GROUNDED_ANSWER", "QUERY_REWRITE", "RERANK"]
