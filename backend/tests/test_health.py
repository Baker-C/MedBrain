"""Proves the app factory boots and /health responds."""

from fastapi.testclient import TestClient

from api.app import create_app


def test_health_returns_200() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
