"""Pass 1 against the shapes the real corpus actually contains.

Every fixture line here was observed in the 17 corpus PDFs: the two numbering variants,
the ALL-CAPS subsection, the unnumbered boxed warning, the table-of-contents footnote
that leaks past the body marker, and the carton text that a looser pattern reads as a
section heading.
"""

import pytest

from carving import body_elements, carve_sections, numbered_heading
from errors import IngestionError
from tests.factories import table, text, title


def test_accepts_both_numbering_variants_and_both_cases() -> None:
    # Most documents; Warfarin_2 and Warfarin_3 use the trailing dot.
    assert numbered_heading("5 WARNINGS AND PRECAUTIONS") is not None
    assert numbered_heading("5.  WARNINGS AND PRECAUTIONS") is not None
    assert numbered_heading("3. DOSAGE FORMS AND STRENGTHS") is not None

    # Level comes from the number, never the case: Warfarin_2 has an ALL-CAPS subsection.
    caps_subsection = numbered_heading("8.1  PREGNANCY")
    assert caps_subsection is not None
    assert caps_subsection.number == "8.1"

    title_subsection = numbered_heading("5.1 Hemorrhage")
    assert title_subsection is not None
    assert title_subsection.number == "5.1"


@pytest.mark.parametrize(
    "carton_line",
    [
        "1 mg:",  # Warfarin.pdf strength list
        "10 mg White (dye",  # Warfarin.pdf carton description
        "3-4 mg",  # Warfarin_2.pdf dosing table cell
        "5 mg",  # bare strength under a display panel
        "30 Tablets",  # Bupropion_2.pdf display panel
        "30 Capsules",  # Escitalopram.pdf display panel
    ],
)
def test_rejects_carton_text_that_looks_numbered(carton_line: str) -> None:
    assert numbered_heading(carton_line) is None


def test_accepts_single_word_section_titles() -> None:
    # `5.1 Hemorrhage` and `11 DESCRIPTION` are ordinary; a word-count rule would have
    # dropped a quarter of the corpus's sections.
    assert numbered_heading("5.1 Hemorrhage") is not None
    assert numbered_heading("11 DESCRIPTION") is not None
    assert numbered_heading("5.4 Proarrhythmia") is not None


def test_body_window_drops_highlights_contents_and_packaging() -> None:
    elements = [
        title("HIGHLIGHTS OF PRESCRIBING INFORMATION", page=1),
        text("Warfarin sodium is an anticoagulant.", page=1),
        title("FULL PRESCRIBING INFORMATION: CONTENTS", page=2),
        text("1 INDICATIONS AND USAGE", page=2),
        title("FULL PRESCRIBING INFORMATION", page=3),
        title("1 INDICATIONS AND USAGE", page=3),
        text("Warfarin sodium is indicated for prophylaxis of thrombosis.", page=3),
        title("PRINCIPAL DISPLAY PANEL - 1 mg Tablet Bottle Label", page=30),
        text("NDC 51407-784-01", page=30),
    ]

    body = body_elements(elements)

    assert [element.text for element in body] == [
        "1 INDICATIONS AND USAGE",
        "Warfarin sodium is indicated for prophylaxis of thrombosis.",
    ]


def test_body_window_requires_the_marker() -> None:
    with pytest.raises(IngestionError, match="FULL PRESCRIBING INFORMATION"):
        body_elements([title("HIGHLIGHTS OF PRESCRIBING INFORMATION"), text("Anything.")])


def test_carves_at_the_finest_heading_and_drops_contents_residue() -> None:
    elements = [
        # Four documents leak this contents footnote past the body marker.
        text("Sections or subsections omitted from the full prescribing information", page=3),
        title("WARNING: BLEEDING RISK", page=3),
        text("Warfarin sodium can cause major or fatal bleeding.", page=3),
        title("5 WARNINGS AND PRECAUTIONS", page=8),
        text("Warfarin is contraindicated in pregnancy.", page=8),
        title("5.1 Hemorrhage", page=8),
        text("Hemorrhage can occur at any site.", page=8),
    ]

    sections = carve_sections(elements)

    assert [(section.number, section.title) for section in sections] == [
        (None, "WARNING: BLEEDING RISK"),
        ("5", "WARNINGS AND PRECAUTIONS"),
        ("5.1", "Hemorrhage"),
    ]
    # The residue precedes the first heading and belongs to no section.
    assert all("omitted from the full" not in e.text for s in sections for e in s.elements)


def test_a_heading_with_no_content_produces_no_section() -> None:
    sections = carve_sections(
        [
            title("5 WARNINGS AND PRECAUTIONS", page=8),
            title("5.1 Hemorrhage", page=8),
            text("Hemorrhage can occur at any site.", page=8),
        ]
    )

    assert [section.number for section in sections] == ["5.1"]


def test_tables_and_untitled_blocks_stay_with_their_section() -> None:
    sections = carve_sections(
        [
            title("2.3 Initial and Maintenance Dosing", page=6),
            title("SUICIDALITY AND ANTIDEPRESSANT DRUGS", page=6),
            table("<table><tr><td>INR</td></tr></table>", page=6),
        ]
    )

    assert len(sections) == 1
    # A title-shaped element that is not a heading is content, not a lost element.
    assert [element.kind for element in sections[0].elements] == ["text", "table"]
