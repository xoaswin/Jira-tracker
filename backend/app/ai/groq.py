"""GroqProvider: free tier, fast, OpenAI-compatible chat completions (section 8).

Opt-in only (sends internal text to a third party). API key lives in the
keychain.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("jira_tracker.ai.groq")

_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-20b"):
        self.api_key = api_key
        self.model = model

    def generate(self, system: str, user: str, max_tokens: int = 512) -> str:
        resp = httpx.post(
            _URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
            },
            # Generous HTTP timeout; the real wall-clock cap is enforced by
            # safe_generate's thread-level timeout, so this only needs to be
            # large enough not to cut a longer generation short.
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content", "").strip()

    def is_available(self) -> bool:
        """Verify the key is valid AND the configured model exists/is accessible,
        so the UI status reflects whether generation will actually work (not just
        that a key was pasted)."""
        if not self.api_key:
            return False
        try:
            resp = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=4.0,
            )
            if resp.status_code != 200:
                return False
            ids = {m.get("id") for m in resp.json().get("data", [])}
            return self.model in ids
        except httpx.HTTPError:
            return False
