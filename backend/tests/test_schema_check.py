"""Proves the schema check catches drift between row models and live columns."""

from healthcheck import expected_column, schema_problems
from persistence.rows import ConversationRow

CONVERSATION_COLUMNS = {
    "id": ("uuid", False),
    "title": ("text", False),
    "created_at": ("timestamp with time zone", False),
}


def test_matching_columns_produce_no_problems() -> None:
    assert schema_problems("conversations", ConversationRow, CONVERSATION_COLUMNS) == []


def test_missing_column_is_flagged() -> None:
    columns = {name: spec for name, spec in CONVERSATION_COLUMNS.items() if name != "title"}
    assert schema_problems("conversations", ConversationRow, columns) == [
        "conversations.title: missing column"
    ]


def test_type_mismatch_is_flagged() -> None:
    columns = CONVERSATION_COLUMNS | {"title": ("integer", False)}
    problems = schema_problems("conversations", ConversationRow, columns)
    assert problems == ["conversations.title: type is integer, model expects text"]


def test_nullability_mismatch_is_flagged() -> None:
    columns = CONVERSATION_COLUMNS | {"title": ("text", True)}
    problems = schema_problems("conversations", ConversationRow, columns)
    assert problems == ["conversations.title: nullable is True, model expects nullable=False"]


def test_optional_field_maps_to_nullable_text() -> None:
    assert expected_column(str | None) == ({"text"}, True)
