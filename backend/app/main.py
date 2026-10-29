"""FastAPI application entry point for TradeMirror.

Responsibility:
Initializes the FastAPI application, mounts the /api router, implements request ID
tracing, per-route cache control headers, safe exception isolation without stack traces,
and single-service static asset serving with SPA routing fallback.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router as api_router
from app.config import settings

logger = logging.getLogger("app.main")

app = FastAPI(
    title="TradeMirror API",
    description="Post-trade behavioural habit review tool for retail F&O traders in India",
    version="0.1.0",
)


@app.middleware("http")
async def request_lifecycle_middleware(request: Request, call_next):
    """Enforce request ID propagation, cache headers, and privacy-respecting audit logging."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    start_time = time.perf_counter()

    response = await call_next(request)

    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id

    # Cache control: no-store on all API endpoints
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"

    row_count = getattr(request.state, "row_count", "-")
    logger.info(
        "request_id=%s route=%s status=%d duration=%.2fms rows=%s",
        request_id,
        request.url.path,
        response.status_code,
        duration_ms,
        row_count,
    )
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with request_id and proper headers."""
    request_id = getattr(request.state, "request_id", "")
    headers = {"X-Request-ID": request_id}
    if exc.status_code == 429 and exc.headers and "Retry-After" in exc.headers:
        headers["Retry-After"] = exc.headers["Retry-After"]

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request_id},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors with request_id."""
    request_id = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc), "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Isolate unexpected server exceptions and return a generic 500 without stack traces."""
    request_id = getattr(request.state, "request_id", "")
    logger.exception("Unhandled server exception [request_id=%s]: %s", request_id, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred.", "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


# Mount API router under /api
app.include_router(api_router, prefix="/api")


# Single-service static serving & SPA fallback
@app.get("/", include_in_schema=False)
def serve_root():
    """Serve frontend index.html if dist exists, or informative API status message."""
    dist_dir = Path(settings.FRONTEND_DIST)
    index_file = dist_dir / "index.html"
    if dist_dir.is_dir() and index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"message": "TradeMirror API is running. Frontend dist not found."})


@app.get("/assets/{asset_path:path}", include_in_schema=False)
def serve_asset(asset_path: str, request: Request):
    """Serve built static assets with long-lived immutable cache control."""
    dist_dir = Path(settings.FRONTEND_DIST)
    assets_dir = (dist_dir / "assets").resolve()
    target_file = (assets_dir / asset_path).resolve()

    if dist_dir.is_dir() and target_file.is_file() and str(target_file).startswith(str(assets_dir)):
        return FileResponse(
            target_file,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    request_id = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=404,
        content={"detail": "Asset not found", "request_id": request_id},
    )


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa_fallback(full_path: str, request: Request):
    """Fallback handler for SPA routing. Unknown /api paths return JSON 404, never index.html."""
    request_id = getattr(request.state, "request_id", "")

    # Unknown /api paths must always return JSON 404, never index.html
    if full_path == "api" or full_path.startswith("api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Not Found", "request_id": request_id},
        )

    dist_dir = Path(settings.FRONTEND_DIST)
    if dist_dir.is_dir():
        candidate = (dist_dir / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(dist_dir.resolve())):
            return FileResponse(candidate)
        index_file = dist_dir / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)

    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found", "request_id": request_id},
    )
