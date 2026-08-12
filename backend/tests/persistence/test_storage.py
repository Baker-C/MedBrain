"""Signed-URL response validation: the SDK's loose dict becomes a typed URL or an error."""

import pytest
from pydantic import ValidationError

from persistence.storage import SignedUrl

CANNED_RESPONSE = {
    "signedURL": "https://acme.supabase.co/storage/v1/object/sign/corpus/Warfarin.pdf?token=abc",
    "signedUrl": "https://acme.supabase.co/storage/v1/object/sign/corpus/Warfarin.pdf?token=abc",
}


def test_signed_url_is_extracted_from_the_sdk_response_dict() -> None:
    assert SignedUrl.model_validate(CANNED_RESPONSE).url == CANNED_RESPONSE["signedURL"]


def test_a_failed_signing_surfaces_as_a_validation_error_not_a_none_url() -> None:
    # storage3 returns {"signedURL": None, "signedUrl": None} when signing fails.
    with pytest.raises(ValidationError):
        SignedUrl.model_validate({"signedURL": None, "signedUrl": None})
