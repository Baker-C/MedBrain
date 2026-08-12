# /// script
# requires-python = ">=3.12"
# dependencies = ["supabase", "python-dotenv"]
# ///
"""One-time local seed: `DocumentCorpus/` PDFs into the private Storage bucket.

Storage only. It never writes the `documents` registry — the ingestion job owns that,
and it reconciles against the bucket rather than against this script, so the bucket
stays the source of truth for what the corpus contains.

Re-running is safe: each object is uploaded with upsert, so the bucket ends in the
same state whether this is the first run or the fifth.

    uv run scripts/upload/upload_corpus.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "DocumentCorpus"
# Must match ingestion's `corpus_bucket` setting and `storage.CORPUS_PREFIX`.
BUCKET = os.environ.get("CORPUS_BUCKET", "corpus")
PREFIX = "documents"


def client_from_env() -> Client:
    """Credentials come from the environment, or from the ingestion job's own .env."""
    load_dotenv(REPO_ROOT / "ingestion" / ".env")
    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not service_key:
        sys.exit("Set SUPABASE_URL and SUPABASE_SERVICE_KEY, or fill in ingestion/.env.")
    return create_client(url, service_key)


def ensure_private_bucket(client: Client) -> None:
    """The bucket is never public: the backend mints short-lived signed URLs instead."""
    existing = {bucket.name for bucket in client.storage.list_buckets()}
    if BUCKET not in existing:
        client.storage.create_bucket(BUCKET, options={"public": False})
        print(f"created private bucket {BUCKET!r}")


def upload_pdf(client: Client, pdf: Path) -> None:
    client.storage.from_(BUCKET).upload(
        f"{PREFIX}/{pdf.name}",
        pdf.read_bytes(),
        {"content-type": "application/pdf", "upsert": "true"},
    )


def main() -> None:
    client = client_from_env()
    ensure_private_bucket(client)

    pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDFs found in {CORPUS_DIR}.")
    for pdf in pdfs:
        upload_pdf(client, pdf)
        print(f"uploaded {PREFIX}/{pdf.name}")
    print(f"{len(pdfs)} PDFs now in {BUCKET}/{PREFIX}. Run the ingestion job next.")


if __name__ == "__main__":
    main()
