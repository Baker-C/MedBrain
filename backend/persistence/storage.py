"""Signed-URL minting against the private corpus bucket.

Click-through citations resolve here: the backend never proxies file bytes, it
mints a short-lived signed URL for `documents.storage_object_key` and the client
follows it straight to Supabase Storage. The ~5-minute TTL and the private bucket
are design decisions from DESIGN.md. The `#page=N` fragment is appended
client-side — fragments never reach the server, so they cannot break the
signature.
"""

from pydantic import BaseModel, Field
from supabase import Client

from config import CORPUS_BUCKET, SIGNED_URL_TTL_SECONDS


# The storage3 sync client returns {"signedURL": <absolute url>, "signedUrl": <same>};
# both keys carry the same value, and both are None when signing failed, so
# validating one of them as a required str is the whole boundary check.
class SignedUrl(BaseModel):
    url: str = Field(alias="signedURL")


def create_source_url(storage: Client, object_key: str) -> str:
    """Mint an absolute, ~5-minute signed URL for one object in the corpus bucket."""
    response = storage.storage.from_(CORPUS_BUCKET).create_signed_url(
        object_key, SIGNED_URL_TTL_SECONDS
    )
    return SignedUrl.model_validate(response).url
