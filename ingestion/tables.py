"""Serialize `hi_res` table HTML into text, and split oversized tables by row groups.

Tables carry the answer in a drug label — dosing by indication, interaction lists — so
they are atomic blocks the recursive splitter never sees. A table that fits is one
chunk; a table that does not is cut between rows with its header row repeated, so no
piece is a grid of numbers with no column names.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser

CELL_SEPARATOR = " | "


@dataclass(frozen=True)
class TableGrid:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


class TableRowParser(HTMLParser):
    """Collect `<tr>` rows and their cell text, ignoring everything else.

    Deliberately indifferent to nesting and to how many `<table>` elements the input
    holds: a stitched cross-page table arrives as two concatenated tables and reads
    back as one ordered list of rows.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cells: list[str] = []
        self._text: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._cells = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False
            self._cells.append(" ".join("".join(self._text).split()))
        elif tag == "tr" and self._cells:
            self.rows.append(self._cells)
            self._cells = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._text.append(data)


def parse_table(html: str) -> TableGrid:
    """First row is the header; later rows identical to it are page-continuation repeats."""
    parser = TableRowParser()
    parser.feed(html)
    if not parser.rows:
        return TableGrid(header=(), rows=())
    header = tuple(parser.rows[0])
    body = tuple(tuple(row) for row in parser.rows[1:] if tuple(row) != header)
    return TableGrid(header=header, rows=body)


def render_row(cells: Sequence[str]) -> str:
    return CELL_SEPARATOR.join(cells)


def render_table(grid: TableGrid) -> str:
    lines = [render_row(grid.header)] if grid.header else []
    lines.extend(render_row(row) for row in grid.rows)
    return "\n".join(lines)


def split_table(grid: TableGrid, budget: int) -> list[str]:
    """One serialization if it fits, otherwise row groups that each repeat the header."""
    whole = render_table(grid)
    if len(whole) <= budget or not grid.rows:
        return [whole]

    header_line = render_row(grid.header)
    pieces: list[str] = []
    group: list[str] = []
    used = len(header_line)
    for row in grid.rows:
        line = render_row(row)
        # +1 for the newline joining this row to the group.
        if group and used + len(line) + 1 > budget:
            pieces.append("\n".join([header_line, *group]))
            group, used = [], len(header_line)
        group.append(line)
        used += len(line) + 1
    if group:
        pieces.append("\n".join([header_line, *group]))
    return pieces
