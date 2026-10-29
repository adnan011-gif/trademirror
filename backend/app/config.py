"""Configuration module for TradeMirror backend settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    LLM_API_KEY: str | None = None
    LLM_MODEL: str = "gpt-4o-mini"
    MAX_UPLOAD_MB: int = 5


settings = Settings()
