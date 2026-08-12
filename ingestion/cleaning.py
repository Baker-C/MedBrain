"""Clean extracted elements: page furniture, PDF hard wraps, cross-page tables.

Runs on the body window only (see `carving.body_elements`). Run against the whole
document it would delete real headings: `WARNINGS AND PRECAUTIONS` appears in
HIGHLIGHTS, in the table of contents, and again in the body — three pages, which is
exactly what the repeated-line rule treats as a running header.
"""

import re
from collections import defaultdict
from collections.abc import Sequence

from models import PageElement

# A short line on three or more pages is running furniture, not content.
FURNITURE_MIN_PAGES = 3
FURNITURE_MAX_LENGTH = 80

SENTENCE_ENDINGS = (".", ":", ";", "?", "!")


def normalize_for_repeat(text: str) -> str:
    """Collapse whitespace and digits so `Reference ID: 4472119` matches across pages."""
    return re.sub(r"\d+", "#", " ".join(text.split())).casefold()


def is_furniture_candidate(element: PageElement) -> bool:
    return element.kind != "table" and len(element.text) <= FURNITURE_MAX_LENGTH


def drop_page_furniture(elements: Sequence[PageElement]) -> list[PageElement]:
    """Drop short lines that repeat across pages — running headers, footers, page numbers."""
    pages_by_line: dict[str, set[int]] = defaultdict(set)
    for element in elements:
        if is_furniture_candidate(element):
            pages_by_line[normalize_for_repeat(element.text)].add(element.page_start)

    furniture = {line for line, pages in pages_by_line.items() if len(pages) >= FURNITURE_MIN_PAGES}
    return [
        element
        for element in elements
        if not is_furniture_candidate(element)
        or normalize_for_repeat(element.text) not in furniture
    ]


def continues_previous_line(previous: str, following: str) -> bool:
    """True when the break between the two lines is a PDF hard wrap, not a real one."""
    return not previous.endswith(SENTENCE_ENDINGS) and following[:1].islower()


def rejoin_hard_wraps(text: str) -> str:
    """Rejoin lines the PDF wrapped mid-sentence, and repair hyphenated splits."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not lines:
            lines.append(line)
        elif lines[-1].endswith("-"):
            lines[-1] = lines[-1][:-1] + line
        elif continues_previous_line(lines[-1], line):
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    return "\n".join(lines)


def continues_table(previous: PageElement, current: PageElement) -> bool:
    """A table broken by a page boundary: the next table block starts on a later page."""
    return (
        previous.kind == "table"
        and current.kind == "table"
        and current.page_start > previous.page_end
    )


def stitch_cross_page_tables(elements: Sequence[PageElement]) -> list[PageElement]:
    """Rejoin table blocks split across a page boundary into one element.

    The merged element spans both pages and its HTML holds both blocks' rows;
    `tables.parse_table` reads rows across them and drops the repeated header row.
    """
    stitched: list[PageElement] = []
    for element in elements:
        if stitched and continues_table(stitched[-1], element):
            previous = stitched[-1]
            stitched[-1] = PageElement(
                kind="table",
                text=f"{previous.text}\n{element.text}",
                page_start=previous.page_start,
                page_end=element.page_end,
                html=(previous.html or "") + (element.html or ""),
            )
        else:
            stitched.append(element)
    return stitched


def clean_elements(elements: Sequence[PageElement]) -> list[PageElement]:
    """Furniture out, hard wraps rejoined, cross-page tables stitched."""
    kept = drop_page_furniture(elements)
    unwrapped = [
        element
        if element.kind == "table"
        else PageElement(
            kind=element.kind,
            text=rejoin_hard_wraps(element.text),
            page_start=element.page_start,
            page_end=element.page_end,
            html=element.html,
        )
        for element in kept
    ]
    # A table's content is its HTML; `hi_res` often leaves such an element's text empty.
    return stitch_cross_page_tables([e for e in unwrapped if e.text.strip() or e.html])
