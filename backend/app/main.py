"""FastAPI application entry point for TradeMirror."""

from fastapi import FastAPI

from app.api.routes import router as api_router

app = FastAPI(
    title="TradeMirror API",
    description="Post-trade behavioural habit review tool for retail F&O traders in India",
    version="0.1.0",
)

app.include_router(api_router, prefix="/api")
