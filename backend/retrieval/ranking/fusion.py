"""Reciprocal Rank Fusion: merges the two candidate lists on rank alone.

Pure — no client, no connection. Rank-based by design, so cosine distance and
ts_rank never have to be reconciled onto a common scale. Agreement compounds: a
chunk both legs return can outscore a chunk that only one leg ranks first.
"""

from persistence.rows import ChunkRow
from retrieval.contract import ScoredChunk


def rank_by_chunk_id(chunks: list[ChunkRow]) -> dict[int, int]:
    """One leg's result list as {chunk id: 1-based rank}."""
    return {chunk.id: rank for rank, chunk in enumerate(chunks, start=1)}


def reciprocal_rank(rank: int | None, rrf_k: int) -> float:
    """A leg's contribution to the fused score; nothing when it did not return the chunk."""
    return 0.0 if rank is None else 1.0 / (rrf_k + rank)


def fuse_rankings(
    dense: list[ChunkRow], sparse: list[ChunkRow], *, rrf_k: int, limit: int
) -> list[ScoredChunk]:
    """Fuse both legs into one list of `limit` candidates, highest score first.

    A single-leg run needs no separate path: reciprocal rank decreases with rank, so
    fusing one list against an empty one reproduces that list's own order. Ties break
    on chunk id, which keeps repeated eval runs identical.
    """
    dense_ranks = rank_by_chunk_id(dense)
    sparse_ranks = rank_by_chunk_id(sparse)
    candidates = {chunk.id: chunk for chunk in [*dense, *sparse]}
    fused = [
        ScoredChunk(
            chunk=chunk,
            dense_rank=dense_ranks.get(chunk_id),
            sparse_rank=sparse_ranks.get(chunk_id),
            rrf_score=reciprocal_rank(dense_ranks.get(chunk_id), rrf_k)
            + reciprocal_rank(sparse_ranks.get(chunk_id), rrf_k),
        )
        for chunk_id, chunk in candidates.items()
    ]
    return sorted(fused, key=lambda scored: (-scored.rrf_score, scored.chunk.id))[:limit]
