"""Furniture removal, hard-wrap repair, and cross-page table stitching."""

from cleaning import (
    clean_elements,
    drop_page_furniture,
    rejoin_hard_wraps,
    stitch_cross_page_tables,
)
from tests.factories import table, text


def test_drops_lines_that_repeat_across_pages() -> None:
    elements = [
        text("Reference ID: 4472119", page=1),
        text("Warfarin sodium is an anticoagulant.", page=1),
        text("Reference ID: 4472120", page=2),
        text("Bleeding risk increases with INR.", page=2),
        text("Reference ID: 4472121", page=3),
    ]

    kept = drop_page_furniture(elements)

    # The trailing digits differ per page; normalizing them is what makes it one line.
    assert [element.text for element in kept] == [
        "Warfarin sodium is an anticoagulant.",
        "Bleeding risk increases with INR.",
    ]


def test_keeps_a_line_that_repeats_on_only_two_pages() -> None:
    elements = [text("Table 1: Dosing", page=1), text("Table 1: Dosing", page=2)]

    assert len(drop_page_furniture(elements)) == 2


def test_rejoins_hard_wraps_and_hyphenation() -> None:
    wrapped = "Warfarin sodium can cause major or\nfatal bleeding.\nMonitor the INR regu-\nlarly."

    assert rejoin_hard_wraps(wrapped) == (
        "Warfarin sodium can cause major or fatal bleeding.\nMonitor the INR regularly."
    )


def test_keeps_a_real_line_break_between_sentences() -> None:
    assert rejoin_hard_wraps("First sentence ends.\nSecond begins.") == (
        "First sentence ends.\nSecond begins."
    )


def test_stitches_a_table_split_across_a_page_boundary() -> None:
    elements = [
        table("<table><tr><td>INR</td><td>Dose</td></tr><tr><td>2.0</td><td>5 mg</td></tr></table>",
              page=17),
        table("<table><tr><td>INR</td><td>Dose</td></tr><tr><td>3.0</td><td>3 mg</td></tr></table>",
              page=18),
        text("py = patient years", page=18),
    ]

    stitched = stitch_cross_page_tables(elements)

    assert len(stitched) == 2
    assert stitched[0].page_start == 17
    assert stitched[0].page_end == 18
    assert "3.0" in (stitched[0].html or "")


def test_two_tables_on_the_same_page_stay_separate() -> None:
    elements = [
        table("<table><tr><td>a</td></tr></table>", page=17),
        table("<table><tr><td>b</td></tr></table>", page=17),
    ]

    assert len(stitch_cross_page_tables(elements)) == 2


def test_clean_elements_leaves_tables_unwrapped() -> None:
    elements = [
        text("Bleeding risk increases with\nrising INR values.", page=4),
        table("<table><tr><td>INR</td></tr></table>", page=4),
    ]

    cleaned = clean_elements(elements)

    assert cleaned[0].text == "Bleeding risk increases with rising INR values."
    assert cleaned[1].html == "<table><tr><td>INR</td></tr></table>"
