"""One question, end to end: retrieval, then generation, then history.

The composition layer. `retrieval/` decides what to answer from, `chat/` turns that
into an answer stream, `persistence/` stores the result — none of the three knows
about the others, and this package is where they meet.

`turn.py` holds the whole arrangement in one function, so the two outcomes retrieval
can return are branched on exactly once no matter how many callers there are;
`contract.py` is the `Turn` they all read; `history.py` adapts between stored messages
and the two packages' own shapes; `persist.py` writes a stream's result as it passes.
"""
