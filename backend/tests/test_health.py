"""Proves the app factory boots and /health responds."""

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


def test_health_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "http://localhost")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
