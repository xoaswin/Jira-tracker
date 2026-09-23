"""NullProvider: the always-available fallback (section 8).

Returns the raw user input unchanged. This is what the app degrades to whenever
the configured provider is unreachable or times out, with a small "AI
unavailable" indicator in the UI rather than an error. It is also the provider
when AI is turned off entirely.
"""

from __future__ import annotations


class NullProvider:
    name = "none"

    def generate(self, system: str, user: str, max_tokens: int = 512) -> str:
        # Return the user's own text so callers can uniformly use the result.
        # We strip a known prefix line if present (the prompts put the raw text
        # after a blank line), otherwise return the input verbatim.
        if "\n\n" in user:
            return user.split("\n\n", 1)[1].strip()
        return user.strip()

    def is_available(self) -> bool:
        return True
