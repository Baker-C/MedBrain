"""Prompt texts, one per module; import them from this package index."""

from prompts.advice_gate import ADVICE_GATE
from prompts.grounded_answer import GROUNDED_ANSWER
from prompts.query_rewrite import QUERY_REWRITE

__all__ = ["ADVICE_GATE", "GROUNDED_ANSWER", "QUERY_REWRITE"]
