"""The diffs that make a re-run idempotent."""

from models import ChunkLocation
from reconciliation import BucketDocument, document_id_for, plan_chunks, plan_corpus
from tests.factories import chunk


def bucket_document(document_id: str, file_sha256: str) -> BucketDocument:
    return BucketDocument(
        document_id=document_id,
        object_key=f"documents/{document_id}.pdf",
        file_sha256=file_sha256,
    )


def location(
    page: int = 1, chunk_index: int = 0, section_number: str | None = "5.1"
) -> ChunkLocation:
    return ChunkLocation(
        section_number=section_number,
        section_title="Hemorrhage",
        page_start=page,
        page_end=page,
        chunk_index=chunk_index,
    )


def test_document_id_comes_from_the_object_key() -> None:
    assert document_id_for("documents/Warfarin_2.pdf") == "Warfarin_2"


def test_corpus_plan_splits_new_unchanged_changed_and_removed() -> None:
    bucket = [
        bucket_document("Warfarin", "hash-warfarin"),
        bucket_document("Apixaban", "hash-apixaban-revised"),
        bucket_document("Digoxin", "hash-digoxin"),
    ]
    registry = {
        "Warfarin": "hash-warfarin",
        "Apixaban": "hash-apixaban",
        "Sertraline": "hash-sertraline",
    }

    plan = plan_corpus(bucket, registry)

    assert [document.document_id for document in plan.ingest] == ["Apixaban", "Digoxin"]
    assert plan.unchanged == ("Warfarin",)
    assert plan.removed == ("Sertraline",)


def test_an_empty_registry_ingests_everything() -> None:
    plan = plan_corpus([bucket_document("Warfarin", "hash")], {})

    assert len(plan.ingest) == 1
    assert plan.unchanged == () and plan.removed == ()


def test_chunk_plan_keeps_inserts_relocates_and_deletes() -> None:
    fresh = [
        chunk("hash-unmoved", page=4, chunk_index=0),
        chunk("hash-moved", page=9, chunk_index=1),
        chunk("hash-new", page=10, chunk_index=2),
    ]
    stored = {
        "hash-unmoved": location(page=4, chunk_index=0),
        "hash-moved": location(page=8, chunk_index=1),
        "hash-orphaned": location(page=12, chunk_index=2),
    }

    plan = plan_chunks(fresh, stored)

    assert [c.content_sha256 for c in plan.insert] == ["hash-new"]
    assert [c.content_sha256 for c in plan.relocate] == ["hash-moved"]
    assert plan.delete == ("hash-orphaned",)
    assert plan.unchanged == ("hash-unmoved",)


def test_a_chunk_that_only_changed_index_still_relocates() -> None:
    # Content is identical, so it keeps its embedding; its position must still be honest.
    plan = plan_chunks(
        [chunk("hash", page=4, chunk_index=7)], {"hash": location(page=4, chunk_index=3)}
    )

    assert [c.content_sha256 for c in plan.relocate] == ["hash"]
    assert plan.insert == ()


def test_reingesting_an_unchanged_document_writes_nothing() -> None:
    fresh = [chunk("hash-a", page=4, chunk_index=0), chunk("hash-b", page=5, chunk_index=1)]
    stored = {"hash-a": location(page=4, chunk_index=0), "hash-b": location(page=5, chunk_index=1)}

    plan = plan_chunks(fresh, stored)

    assert plan.insert == () and plan.relocate == () and plan.delete == ()
    assert len(plan.unchanged) == 2
