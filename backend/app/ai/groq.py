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

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 700,
    ) -> dict:
        """Multi-turn chat with optional tool-calling (assistant feature).

        Unlike ``generate`` (a single system+user turn for the narrow "improve
        wording" helpers), this passes a full ``messages`` array and, when
        ``tools`` are given, lets the model return ``tool_calls`` so the app can
        propose an action. Returns a plain dict ``{content, tool_calls}``;
        ``app.ai.chat.safe_chat`` normalises and timeout-guards it.
        """
        body: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        resp = httpx.post(
            _URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return {"content": "", "tool_calls": []}
        # Return the raw assistant message so tool_call ids survive: the agentic
        # loop must echo this message back and answer each call by id.
        return choices[0].get("message") or {"content": "", "tool_calls": []}

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
