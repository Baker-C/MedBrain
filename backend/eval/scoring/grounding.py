"""The grounding check: every citation the answer emitted resolves to a served chunk.

A tag missing from the sources mapping is a hallucinated citation — the model wrote
`[[S9]]` when no ninth excerpt existed.
"""

from collections.abc import Mapping, Sequence

from chat.contract import Citation


def unresolved_tags(tags: Sequence[str], sources: Mapping[str, Citation]) -> list[str]:
    """The emitted tags with no citation behind them, in emission order; empty passes."""
    return [tag for tag in tags if tag not in sources]
