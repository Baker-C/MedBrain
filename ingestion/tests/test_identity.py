"""Identity extraction: what the model returns, and every way it can be unusable.

`with_structured_output` is typed as returning `dict | BaseModel`, so the narrowing is
the part worth testing — an off-schema response must fail the document rather than
register it under a guess.
"""

from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from errors import IngestionError
from identity import DocumentIdentity, build_identity_input, extract_identity
from tests.factories import text

WARFARIN = DocumentIdentity(
    drug_name="warfarin", manufacturer="New Horizon Rx Group, LLC", formulation="tablet"
)


class _IdentityModel:
    """Stands in for `ChatOpenAI`; only these two methods are reached from identity.py."""

    def __init__(self, result: object) -> None:
        self._result = result

    def with_structured_output(self, schema: type[BaseModel], **kwargs: object) -> "_IdentityModel":
        return self

    def invoke(self, input: list[BaseMessage], **kwargs: object) -> object:
        return self._result


def as_model(result: object) -> BaseChatModel:
    return cast(BaseChatModel, _IdentityModel(result))


def test_returns_the_parsed_identity() -> None:
    identity = extract_identity(as_model(WARFARIN), "Warfarin_2", [text("WARFARIN SODIUM")])

    assert identity.drug_name == "warfarin"
    assert identity.formulation == "tablet"


def test_an_off_schema_response_fails_the_document() -> None:
    # The dict half of `dict | BaseModel`: structured output that did not bind.
    with pytest.raises(IngestionError, match="not a document identity"):
        extract_identity(as_model({"drug_name": "warfarin"}), "Warfarin_2", [text("x")])


@pytest.mark.parametrize(
    "identity",
    [
        DocumentIdentity(drug_name="  ", manufacturer="Teva", formulation=None),
        DocumentIdentity(drug_name="warfarin", manufacturer="", formulation=None),
    ],
)
def test_an_empty_required_field_fails_the_document(identity: DocumentIdentity) -> None:
    with pytest.raises(IngestionError, match="drug name or manufacturer"):
        extract_identity(as_model(identity), "Warfarin_2", [text("x")])


def test_identity_input_samples_both_ends_of_a_long_label() -> None:
    elements = [text("A" * 4000), text("B" * 4000)]

    sampled = build_identity_input(elements)

    # The title block and the labeler statement sit at opposite ends of a label.
    assert sampled.startswith("A")
    assert sampled.endswith("B")
    assert "[...]" in sampled
