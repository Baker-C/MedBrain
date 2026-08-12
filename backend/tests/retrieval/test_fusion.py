"""RRF fusion: agreement compounds, a single leg passes through, and the cut applies."""

from collections.abc import Callable

from persistence.rows import ChunkRow
from retrieval.ranking.fusion import fuse_rankings

RRF_K = 60


def test_agreement_outranks_a_single_leg_top_hit(make_chunk: Callable[[int], ChunkRow]) -> None:
    """The whole reason to fuse: a chunk both legs found beats one only dense ranked first."""
    agreed, dense_only = make_chunk(1), make_chunk(2)
    fused = fuse_rankings([dense_only, agreed], [agreed], rrf_k=RRF_K, limit=10)
    assert [scored.chunk.id for scored in fused] == [1, 2]
    assert (fused[0].dense_rank, fused[0].sparse_rank) == (2, 1)


def test_a_single_leg_keeps_its_own_order(make_chunk: Callable[[int], ChunkRow]) -> None:
    """Dense and sparse modes need no separate path through fusion."""
    fused = fuse_rankings([make_chunk(3), make_chunk(1)], [], rrf_k=RRF_K, limit=10)
    assert [scored.chunk.id for scored in fused] == [3, 1]
    assert all(scored.sparse_rank is None for scored in fused)


def test_limit_cuts_the_fused_list(make_chunk: Callable[[int], ChunkRow]) -> None:
    dense = [make_chunk(chunk_id) for chunk_id in range(1, 6)]
    fused = fuse_rankings(dense, [], rrf_k=RRF_K, limit=2)
    assert [scored.chunk.id for scored in fused] == [1, 2]
