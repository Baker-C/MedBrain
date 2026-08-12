"""The grounding check flags tags that resolve to no served chunk."""

from chat.contract import Citation
from eval.scoring.grounding import unresolved_tags

CITATION = Citation(
    document_id="Warfarin",
    drug="warfarin",
    section_number="5.1",
    section_title="Hemorrhage",
    page_start=7,
)


def test_resolving_tags_pass() -> None:
    assert unresolved_tags(["S1", "S2"], {"S1": CITATION, "S2": CITATION}) == []


def test_invented_tag_is_flagged() -> None:
    assert unresolved_tags(["S1", "S9"], {"S1": CITATION}) == ["S9"]
