"""Table serialization and row-group splitting."""

from tables import parse_table, render_table, split_table

TWO_ROWS = (
    "<table><tr><th>INR</th><th>Dose</th></tr>"
    "<tr><td>2.0-3.0</td><td>5 mg</td></tr></table>"
)


def test_parses_header_and_rows() -> None:
    grid = parse_table(TWO_ROWS)

    assert grid.header == ("INR", "Dose")
    assert grid.rows == (("2.0-3.0", "5 mg"),)
    assert render_table(grid) == "INR | Dose\n2.0-3.0 | 5 mg"


def test_drops_the_header_repeated_by_a_page_continuation() -> None:
    # What stitching produces: two tables concatenated, the second repeating the header.
    continuation = (
        "<table><tr><th>INR</th><th>Dose</th></tr><tr><td>3.1</td><td>3 mg</td></tr></table>"
    )
    stitched = TWO_ROWS + continuation

    grid = parse_table(stitched)

    assert grid.header == ("INR", "Dose")
    assert grid.rows == (("2.0-3.0", "5 mg"), ("3.1", "3 mg"))


def test_a_table_that_fits_stays_atomic() -> None:
    assert len(split_table(parse_table(TWO_ROWS), budget=1500)) == 1


def test_an_oversized_table_splits_by_row_groups_repeating_the_header() -> None:
    rows = "".join(f"<tr><td>row{index}</td><td>{'v' * 40}</td></tr>" for index in range(20))
    grid = parse_table(f"<table><tr><th>Drug</th><th>Effect</th></tr>{rows}</table>")

    pieces = split_table(grid, budget=300)

    assert len(pieces) > 1
    assert all(piece.startswith("Drug | Effect") for piece in pieces)
    # No row is lost and none is duplicated across the pieces.
    assert sum(piece.count("row") for piece in pieces) == 20


def test_a_table_with_no_rows_serializes_to_nothing() -> None:
    assert render_table(parse_table("<p>not a table</p>")) == ""
