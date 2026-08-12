"""Embedding: the pairing guard, which is the part a wrong answer would survive."""

from typing import cast

import pytest
from langchain_core.embeddings import Embeddings

from embedding import embed_texts
from errors import IngestionError


class _Embeddings:
    """Returns a fixed number of vectors, regardless of how many texts it was given."""

    def __init__(self, returned: int) -> None:
        self._returned = returned

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in range(self._returned)]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]


def as_embeddings(returned: int) -> Embeddings:
    return cast(Embeddings, _Embeddings(returned))


def test_embeds_in_input_order() -> None:
    assert len(embed_texts(as_embeddings(2), ["first", "second"])) == 2


def test_a_short_response_fails_rather_than_mispairing() -> None:
    # Vectors are zipped with chunks at insert time; two of three would silently
    # attach the wrong embedding to a chunk.
    with pytest.raises(IngestionError, match="Embedded 2 of 3"):
        embed_texts(as_embeddings(2), ["first", "second", "third"])


def test_no_new_chunks_makes_no_call() -> None:
    # A revised document can need only relocations and deletions.
    assert embed_texts(as_embeddings(3), []) == []
