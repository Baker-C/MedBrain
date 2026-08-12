"""Adapter: Unstructured `hi_res` extraction, reduced to `PageElement`.

The only module that imports Unstructured, and the reason every stage after it is
testable without a PDF. `hi_res` runs local CV layout models: it recovers tables as
structured HTML, which is where most of a drug label's answers live, and it labels
running headers and footers so the obvious page furniture never reaches cleaning.

Unstructured ships no type information, so its output is re-typed at this boundary
against the two protocols below. The untyped import stops on this line.
"""

import io
from collections.abc import Sequence
from typing import Protocol

from unstructured.partition.pdf import partition_pdf

from errors import IngestionError
from models import ElementKind, PageElement

# Images are discarded by design; headers and footers are page furniture the layout
# model already identified.
DISCARDED_CATEGORIES = frozenset(
    {"Image", "Figure", "FigureCaption", "PageBreak", "Header", "Footer"}
)


class ElementMetadata(Protocol):
    page_number: int | None
    text_as_html: str | None


class ExtractedElement(Protocol):
    category: str
    text: str
    metadata: ElementMetadata


def element_kind(category: str) -> ElementKind | None:
    """None means the element is dropped before anything downstream sees it."""
    if category in DISCARDED_CATEGORIES:
        return None
    if category == "Table":
        return "table"
    if category == "Title":
        return "title"
    return "text"


def page_of(element: ExtractedElement) -> int:
    page = element.metadata.page_number
    if page is None:
        raise IngestionError(
            f"Element {element.text[:60]!r} carries no page number; page is the citation floor."
        )
    return page


def to_page_element(element: ExtractedElement) -> PageElement | None:
    kind = element_kind(element.category)
    text = (element.text or "").strip()
    html = element.metadata.text_as_html if kind == "table" else None
    if kind is None or (not text and not html):
        return None
    page = page_of(element)
    return PageElement(kind=kind, text=text, page_start=page, page_end=page, html=html)


def extract_elements(pdf: bytes) -> list[PageElement]:
    """Layout-aware extraction of one PDF, in reading order."""
    elements: Sequence[ExtractedElement] = partition_pdf(
        file=io.BytesIO(pdf),
        strategy="hi_res",
        infer_table_structure=True,
        languages=["eng"],
    )
    reduced = (to_page_element(element) for element in elements)
    return [element for element in reduced if element is not None]
