"""API route definitions for TradeMirror."""

from fastapi import APIRouter

from app.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return API health status."""
    return HealthResponse(status="ok")
