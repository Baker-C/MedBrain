"""Grounded generation and the streaming contract.

`context.py` assembles retrieved chunks into tagged excerpts and the tag->citation
mapping; `events.py` defines the SSE events and their wire form; `generation.py` makes
the streaming model call; `answer.py` composes them into the event stream the endpoint
serves and the trace payload the eval harness consumes.
"""
