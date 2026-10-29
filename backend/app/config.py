"""Configuration module for TradeMirror backend settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    LLM_API_KEY: str | None = None
    LLM_PROVIDER: str = "none"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 20.0
    MAX_UPLOAD_MB: int = 5
    RATE_LIMIT_PER_MINUTE: int = 30
    MAX_ROWS: int = 20000
    SAMPLES_DIR: Path = _REPO_ROOT / "data" / "datasets"
    FRONTEND_DIST: Path = _REPO_ROOT / "frontend" / "dist"


settings = Settings()
