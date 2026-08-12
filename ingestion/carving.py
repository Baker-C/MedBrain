"""Pass 1: carve a PLR label into real sections, and drop what must never be indexed.

The boundary rules here were validated against all 17 corpus documents:

* The body opens after the last element whose text is exactly
  `FULL PRESCRIBING INFORMATION`. Everything before it is the HIGHLIGHTS summary and
  the table of contents — both excluded by design (DESIGN.md, Ingestion).
* The body closes at the first packaging heading. Warfarin.pdf proves packaging is
  terminal: eleven `PRINCIPAL DISPLAY PANEL` blocks and the product-data tables run
  to the last page with no prescribing content after them.
* A heading's level comes from the shape of its number, never from its case:
  `8.1  PREGNANCY` is an ALL-CAPS subsection in Warfarin_2.
* The numbered pattern alone matches carton text (`1 mg:`, `10 mg White (dye`), so a
  heading must also read like a title. Those two lines shape every extra condition in
  `numbered_heading`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from errors import IngestionError
from models import PageElement, Section

BODY_START_MARKER = "FULL PRESCRIBING INFORMATION"
MAX_HEADING_LENGTH = 90
MIN_HEADING_TITLE_CHARS = 3
# PLR defines the numbered sections as 1 through 17. Beyond that it is carton text:
# `30 Tablets` and `30 Capsules` appear on the display panels of four documents.
MAX_SECTION_NUMBER = 17
HEADING_TERMINATORS = (".", ",", ";", ":")

NUMBERED_HEADING = re.compile(r"^(\d{1,2})(?:\.(\d{1,2}))?\.?[ \t]+([A-Z].*)$")
PACKAGING_HEADING = re.compile(
    r"^(principal display panel|package label|ingredients and appearance|product information)",
    re.IGNORECASE,
)
# Unnumbered sections that are real content: boxed warnings and the patient-facing
# blocks that follow section 17. Matched only on elements the extractor called a title.
UNNUMBERED_HEADING = re.compile(
    r"^(warning:|warning\b|boxed warning\b|medication guide\b|patient information\b"
    r"|instructions for use\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Heading:
    number: str | None
    title: str


def numbered_heading(text: str) -> Heading | None:
    """`5.1 Hemorrhage` and `5.  WARNINGS` are headings; `1 mg:` and `3-4 mg` are not."""
    line = text.strip()
    if len(line) > MAX_HEADING_LENGTH or "\n" in line or line.endswith(HEADING_TERMINATORS):
        return None
    match = NUMBERED_HEADING.match(line)
    if match is None:
        return None
    title = match.group(3).strip()
    # Single-word titles are ordinary here (`5.1 Hemorrhage`, `11 DESCRIPTION`), so
    # length is the only floor. Carton text is already excluded by the uppercase
    # first letter and the terminator rule.
    if len(title) < MIN_HEADING_TITLE_CHARS:
        return None
    major, minor, _ = match.groups()
    if not 1 <= int(major) <= MAX_SECTION_NUMBER:
        return None
    return Heading(number=major if minor is None else f"{major}.{minor}", title=title)


def unnumbered_heading(element: PageElement) -> Heading | None:
    """Boxed warnings and patient-facing blocks carry no number, so nothing to parse."""
    line = element.text.strip()
    if element.kind != "title" or len(line) > MAX_HEADING_LENGTH or "\n" in line:
        return None
    if UNNUMBERED_HEADING.match(line) is None:
        return None
    return Heading(number=None, title=line)


def heading_of(element: PageElement) -> Heading | None:
    """Tables are never headings; a numbered heading counts whatever the extractor called it."""
    if element.kind == "table":
        return None
    return numbered_heading(element.text) or unnumbered_heading(element)


def is_body_start(element: PageElement) -> bool:
    """Exact match only — `FULL PRESCRIBING INFORMATION: CONTENTS` heads the contents page."""
    return element.text.strip() == BODY_START_MARKER


def is_packaging(element: PageElement) -> bool:
    return PACKAGING_HEADING.match(element.text.strip()) is not None


def body_elements(elements: Sequence[PageElement]) -> list[PageElement]:
    """The window between the body marker and the packaging sections."""
    starts = [index for index, element in enumerate(elements) if is_body_start(element)]
    if not starts:
        raise IngestionError(
            f"No {BODY_START_MARKER!r} marker found; the document is not a PLR label, and "
            "indexing it would index its HIGHLIGHTS summary and table of contents."
        )
    body = elements[starts[-1] + 1 :]
    packaging = next(
        (index for index, element in enumerate(body) if is_packaging(element)), len(body)
    )
    return list(body[:packaging])


def as_content(element: PageElement) -> PageElement:
    """A title-shaped element that is not a heading is content, not a lost element."""
    if element.kind != "title":
        return element
    return PageElement(
        kind="text",
        text=element.text,
        page_start=element.page_start,
        page_end=element.page_end,
        html=element.html,
    )


def carve_sections(elements: Sequence[PageElement]) -> list[Section]:
    """Split the body at every heading, finest level wins.

    A top-level section with subsections keeps only the text before its first one, so
    `5.1 Hemorrhage` is its own section rather than part of a 20-page section 5.
    Content before the first heading is table-of-contents residue and is dropped.
    """
    sections: list[Section] = []
    heading: Heading | None = None
    content: list[PageElement] = []

    for element in elements:
        found = heading_of(element)
        if found is not None:
            if heading is not None:
                sections.append(Section(heading.number, heading.title, tuple(content)))
            heading, content = found, []
        elif heading is not None:
            content.append(as_content(element))

    if heading is not None:
        sections.append(Section(heading.number, heading.title, tuple(content)))
    return [section for section in sections if section.elements]
