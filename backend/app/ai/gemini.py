"""GeminiProvider: Google AI Studio free tier (section 8).

Opt-in only: this sends internal text to a third party, so the settings screen
must warn clearly and default to Ollama. The API key lives in the keychain, not
in config or the database.
"""

from __future__ import annotations

import logging

import httpx

from app.ai.base import AI_TIMEOUT_SECONDS

logger = logging.getLogger("jira_tracker.ai.gemini")

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model

    def generate(self, system: str, user: str, max_tokens: int = 512) -> str:
        resp = httpx.post(
            f"{_BASE}/{self.model}:generateContent",
            params={"key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
            timeout=AI_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts).strip()

    def is_available(self) -> bool:
        return bool(self.api_key)
