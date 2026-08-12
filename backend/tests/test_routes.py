"""Route-level contracts: the flat conversation-detail shape and the typed response
when OpenAI fails before a stream starts. Adapters and clients are monkeypatched —
these tests prove the wiring and the wire shapes, not SQL or model calls."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openai import OpenAIError

from api.app import create_app
from api.dependencies import db_connection
from persistence.rows import ConversationRow

CONVERSATION_ID = uuid4()


def conversation_row() -> ConversationRow:
    return ConversationRow(
        id=CONVERSATION_ID,
        title="Warfarin questions",
        created_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """An app whose connection dependency is a dummy — every adapter call in these
    tests is monkeypatched, so nothing ever touches it."""
    monkeypatch.setenv("SUPABASE_URL", "http://localhost")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "api.routes.conversations.get_conversation", lambda conn, cid: conversation_row()
    )
    monkeypatch.setattr("api.routes.conversations.list_messages", lambda conn, cid: [])
    app = create_app()
    app.dependency_overrides[db_connection] = lambda: object()
    return TestClient(app)


def test_conversation_detail_is_flat_as_the_frontend_contract_pins(client: TestClient) -> None:
    """`frontend/src/api/types.ts` declares `ConversationDetail extends Conversation`
    and the client caches details keyed on `detail.id` — a nested row breaks the view."""
    response = client.get(f"/conversations/{CONVERSATION_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(CONVERSATION_ID)
    assert body["title"] == "Warfarin questions"
    assert body["messages"] == []
    assert "conversation" not in body


def test_an_openai_failure_before_the_stream_is_a_typed_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stream has not started yet, so the failure is an HTTP error the UI can
    show — not a stack trace and not a broken stream."""
    monkeypatch.setattr("api.routes.app_clients", lambda request: object())

    async def failing_retrieve(*args: object) -> object:
        raise OpenAIError("upstream down")

    monkeypatch.setattr("api.routes.retrieve", failing_retrieve)
    response = client.post(
        f"/conversations/{CONVERSATION_ID}/query", json={"question": "warfarin bleeding risk?"}
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "language model unavailable"}
