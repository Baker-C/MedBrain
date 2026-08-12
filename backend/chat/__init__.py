"""Grounded generation: retrieved chunks in, an answer stream out.

`contract.py` is the vocabulary callers speak — the retrieved chunk going in, the four
events coming out, and the answer a finished stream folds into. Behind it: `join.py`
pairs retrieved chunks with their documents, `context.py` assembles them into tagged
excerpts and the tag->citation mapping, `generation.py` makes the streaming model call,
`stream.py` produces the events, and `collect.py` folds them back.

The package knows nothing about how an event reaches a client, nor about conversations
or history — composing this with retrieval and persistence is `conversation/`'s job.
"""
