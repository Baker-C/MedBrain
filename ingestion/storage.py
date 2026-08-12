"""Adapter: the private Supabase Storage bucket that holds the corpus PDFs.

The bucket is the source of truth for what the corpus contains — `DocumentCorpus/` in
the repo is only the seed the upload script pushes up. File bytes live here and never
in Postgres; the registry stores the object key, and the backend mints signed URLs
against it when a citation is clicked.
"""

from supabase import Client, create_client

CORPUS_PREFIX = "documents"


def storage_client(url: str, service_key: str) -> Client:
    return create_client(url, service_key)


def list_corpus_objects(client: Client, bucket: str) -> list[str]:
    """Object keys of every corpus PDF, sorted so a run's report reads the same each time."""
    # One page of results, which is the whole corpus at this size. A corpus past the
    # API's default page limit would need paging here.
    entries = client.storage.from_(bucket).list(CORPUS_PREFIX)
    names = [str(entry["name"]) for entry in entries]
    return sorted(
        f"{CORPUS_PREFIX}/{name}" for name in names if name.lower().endswith(".pdf")
    )


def download_object(client: Client, bucket: str, object_key: str) -> bytes:
    return client.storage.from_(bucket).download(object_key)
