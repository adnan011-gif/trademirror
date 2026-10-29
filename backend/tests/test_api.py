"""Integration tests for TradeMirror API endpoints."""

from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    """Verify GET /api/health returns 200 and ok status."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
