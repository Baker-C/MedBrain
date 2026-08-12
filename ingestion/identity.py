"""Adapter: the document's own identity, read once per document.

`drug_name` and `manufacturer` are NOT NULL on `documents` and are what a citation
shows, so this fails loudly rather than registering a document under a guess. It runs
once per new or changed document — never per query — on the opening and closing text,
where the product title and the manufacturer statement live.

`with_structured_output` is annotated as returning `dict | BaseModel`, so the result is
narrowed with `isinstance` rather than cast. Anything off-schema takes the same path as
a failed call: this document does not get registered.
"""

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel, SecretStr

from errors import IngestionError
from models import PageElement
from prompts import DOCUMENT_IDENTITY

IDENTITY_MODEL = "gpt-5-mini"
IDENTITY_SAMPLE_CHARS = 3000


class DocumentIdentity(BaseModel):
    drug_name: str
    manufacturer: str
    formulation: str | None


def build_identity_model(api_key: str) -> ChatOpenAI:
    """No temperature: the gpt-5 family only accepts its default."""
    return ChatOpenAI(model=IDENTITY_MODEL, api_key=SecretStr(api_key))


def build_identity_input(elements: Sequence[PageElement]) -> str:
    """The label's opening and closing text — the title block and the labeler statement."""
    text = "\n".join(element.text for element in elements if element.text)
    if len(text) <= 2 * IDENTITY_SAMPLE_CHARS:
        return text
    return f"{text[:IDENTITY_SAMPLE_CHARS]}\n[...]\n{text[-IDENTITY_SAMPLE_CHARS:]}"


def build_identity_messages(elements: Sequence[PageElement]) -> list[BaseMessage]:
    return [
        SystemMessage(content=DOCUMENT_IDENTITY),
        HumanMessage(content=build_identity_input(elements)),
    ]


def extract_identity(
    model: BaseChatModel, document_id: str, elements: Sequence[PageElement]
) -> DocumentIdentity:
    structured = model.with_structured_output(DocumentIdentity)
    try:
        parsed = structured.invoke(build_identity_messages(elements))
    except OpenAIError as error:
        raise IngestionError(f"Could not identify {document_id}: {error}") from error

    if not isinstance(parsed, DocumentIdentity):
        raise IngestionError(
            f"Could not identify {document_id}: the model returned "
            f"{type(parsed).__name__}, not a document identity."
        )
    if not parsed.drug_name.strip() or not parsed.manufacturer.strip():
        raise IngestionError(
            f"Could not identify {document_id}: no usable drug name or manufacturer, "
            "and both are what its citations would show."
        )
    return parsed
