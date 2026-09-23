"""OllamaProvider: the default, fully-local provider (section 8).

POSTs to ``{ollama_url}/api/generate``. Nothing leaves the machine, which is why
this is the default: work descriptions and ticket text are internal company
information (section 8). Model is configurable, default ``llama3.1:8b``.
"""

from __future__ import annotations

import logging

import httpx

from app.ai.base import AI_TIMEOUT_SECONDS

logger = logging.getLogger("jira_tracker.ai.ollama")


class OllamaProvider:
    name = "ollama"

    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model

    def generate(self, system: str, user: str, max_tokens: int = 512) -> str:
        resp = httpx.post(
            f"{self.url}/api/generate",
            json={
                "model": self.model,
                "system": system,
                "prompt": user,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            timeout=AI_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("response") or "").strip()

    def is_available(self) -> bool:
        """Cheap liveness check: is the Ollama server answering?"""
        try:
            resp = httpx.get(f"{self.url}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
