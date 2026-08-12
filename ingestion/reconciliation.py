"""What a re-run must do, decided as pure functions over hashes.

Two levels, both driven off the `documents` registry:

* corpus level — the bucket against the registry, so an unchanged document skips the
  expensive `hi_res` extraction entirely and a deleted one takes its chunks with it;
* chunk level — the freshly chunked document against what is stored for it, so a
  revision re-embeds only what actually changed.

Kept chunks can still have moved. A chunk whose content is identical but whose page
differs is relocated, never re-embedded: the embedding depends on content alone, but
the citation depends on the page.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from models import Chunk, ChunkLocation, location_of


@dataclass(frozen=True)
class BucketDocument:
    """A corpus PDF as the bucket presents it, once its bytes have been hashed."""

    document_id: str
    object_key: str
    file_sha256: str


@dataclass(frozen=True)
class CorpusPlan:
    ingest: tuple[BucketDocument, ...]
    unchanged: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True)
class ChunkPlan:
    insert: tuple[Chunk, ...]
    relocate: tuple[Chunk, ...]
    delete: tuple[str, ...]
    unchanged: tuple[str, ...]


def document_id_for(object_key: str) -> str:
    """`documents/Warfarin_2.pdf` is document `Warfarin_2` — stable and readable in a citation."""
    return PurePosixPath(object_key).stem


def plan_corpus(bucket: Sequence[BucketDocument], registry: Mapping[str, str]) -> CorpusPlan:
    """New and changed documents ingest; byte-identical ones skip; absent ones are removed."""
    present = {document.document_id for document in bucket}
    return CorpusPlan(
        ingest=tuple(d for d in bucket if registry.get(d.document_id) != d.file_sha256),
        unchanged=tuple(
            d.document_id for d in bucket if registry.get(d.document_id) == d.file_sha256
        ),
        removed=tuple(
            sorted(document_id for document_id in registry if document_id not in present)
        ),
    )


def plan_chunks(fresh: Sequence[Chunk], stored: Mapping[str, ChunkLocation]) -> ChunkPlan:
    """Keep what is unchanged, relocate what only moved, insert what is new, delete orphans."""
    kept = [chunk for chunk in fresh if chunk.content_sha256 in stored]
    fresh_hashes = {chunk.content_sha256 for chunk in fresh}
    return ChunkPlan(
        insert=tuple(chunk for chunk in fresh if chunk.content_sha256 not in stored),
        relocate=tuple(c for c in kept if stored[c.content_sha256] != location_of(c)),
        delete=tuple(sorted(h for h in stored if h not in fresh_hashes)),
        unchanged=tuple(
            c.content_sha256 for c in kept if stored[c.content_sha256] == location_of(c)
        ),
    )
