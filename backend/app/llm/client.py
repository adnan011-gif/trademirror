"""Unified LLM Client wrapper for TradeMirror narrative layer.

Responsibility:
Calls configured LLM provider (Gemini or Anthropic) using httpx with a timeout.
Never makes network calls if provider is 'none' or if no API key is set.
Never logs API keys or full prompt bodies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


def call_llm(
    system: str,
    user: str,
    settings: Settings,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Execute a single generation call to the configured LLM provider.

    Args:
        system: System instructions for grounding and persona.
        user: User message containing facts JSON payload and optional retry notes.
        settings: Application settings with LLM configuration.
        transport: Optional httpx transport override (used for test mocking).

    Returns:
        Raw string output from the LLM provider.

    Raises:
        ValueError: If provider is 'none', API key is missing, or provider is unsupported.
        httpx.HTTPError: If the remote HTTP request fails or times out.
    """
    provider = (settings.LLM_PROVIDER or "none").lower().strip()
    api_key = settings.LLM_API_KEY
    model = settings.LLM_MODEL
    timeout = settings.LLM_TIMEOUT_SECONDS

    if provider == "none" or not api_key:
        raise ValueError(
            f"LLM calls disabled: provider is '{provider}' or API key is not configured"
        )

    logger.info("Calling LLM provider '%s' with model '%s'", provider, model)

    client_kwargs: dict[str, object] = {"timeout": timeout}
    if transport is not None:
        client_kwargs["transport"] = transport

    with httpx.Client(**client_kwargs) as client:
        if provider == "gemini":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            payload = {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.0},
            }
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return str(data["candidates"][0]["content"]["parts"][0]["text"])

        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": model,
                "max_tokens": 1024,
                "temperature": 0.0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return str(data["content"][0]["text"])

        raise ValueError(f"Unsupported LLM provider: '{provider}'")


class LLMClient:
    """Convenience wrapper around call_llm preserving legacy interface."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model
