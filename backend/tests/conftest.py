"""Shared test fixtures for TradeMirror backend tests."""

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """TestClient fixture for FastAPI endpoints."""
    return TestClient(app)
