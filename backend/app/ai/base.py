"""AI provider interface (section 8).

The app must be fully functional with AI completely disabled. AI improves wording;
it is never load bearing. Every provider implements the same tiny Protocol, and
every call has a hard 10 second timeout with a fallback to NullProvider, so the
user never waits on a model to log their work.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Hard timeout for any AI generation (section 8). The user never waits longer.
AI_TIMEOUT_SECONDS = 10.0


@runtime_checkable
class AIProvider(Protocol):
    def generate(self, system: str, user: str, max_tokens: int = 512) -> str: ...

    def is_available(self) -> bool: ...
