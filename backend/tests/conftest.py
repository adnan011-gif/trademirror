import httpx
import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no tests can make unmocked external network calls."""

    def _block(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Real network calls are disabled in test suite")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _block)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _block)


@pytest.fixture
def client() -> TestClient:
    """TestClient fixture for FastAPI endpoints."""
    return TestClient(app)
