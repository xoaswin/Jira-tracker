"""Build the configured AI provider and run it safely (section 8).

``get_provider`` reads the settings row to construct the selected provider
(defaulting to Ollama, with third-party keys pulled from the keychain).

``safe_generate`` is the ONLY function callers should use to run a generation.
It enforces the two section-8 guarantees:

* a hard 10 second timeout (the user never waits on a model),
* a silent fallback to NullProvider on ANY failure (timeout, network, provider
  error, or AI simply disabled),

returning ``(text, used_ai)`` so the UI can show a small "AI unavailable"
indicator without anything throwing.
"""

from __future__ import annotations

import concurrent.futures
import logging

from sqlalchemy.orm import Session

from app.ai.base import AI_TIMEOUT_SECONDS, AIProvider
from app.ai.gemini import GeminiProvider
from app.ai.groq import GroqProvider
from app.ai.null import NullProvider
from app.ai.ollama import OllamaProvider
from app.models import AppSettings
from app.secrets import GEMINI_API_KEY, GROQ_API_KEY, get_secret_store

logger = logging.getLogger("jira_tracker.ai")


def get_provider(db: Session) -> AIProvider:
    """Construct the configured provider, or NullProvider if disabled/misconfigured."""
    row = db.get(AppSettings, 1)
    if row is None:
        return NullProvider()

    provider = (row.ai_provider or "none").strip().lower()
    if provider == "ollama":
        return OllamaProvider(
            row.ollama_url or "http://localhost:11434",
            row.ollama_model or "llama3.1:8b",
        )
    if provider == "gemini":
        key = get_secret_store().get(GEMINI_API_KEY)
        return GeminiProvider(key) if key else NullProvider()
    if provider == "groq":
        key = get_secret_store().get(GROQ_API_KEY)
        return GroqProvider(key) if key else NullProvider()
    return NullProvider()


def safe_generate(
    provider: AIProvider,
    system: str,
    user: str,
    *,
    max_tokens: int = 512,
    timeout: float | None = None,
) -> tuple[str, bool]:
    """Run ``provider.generate`` with a timeout and NullProvider fallback.

    Returns ``(text, used_ai)``. ``used_ai`` is False whenever we fell back, so
    the caller can surface an "AI unavailable" hint. Never raises.

    ``timeout`` overrides the default. The 10s default guards the worklog path
    ("never wait on a model to log my work"); deliberate actions like issue
    drafting can pass a longer value.
    """
    limit = timeout if timeout is not None else AI_TIMEOUT_SECONDS
    null = NullProvider()
    if isinstance(provider, NullProvider):
        return null.generate(system, user, max_tokens), False

    # Run in a thread so a slow/hung provider cannot exceed the wall-clock
    # timeout even if its own client ignores it. We deliberately do NOT use the
    # executor as a context manager: its __exit__ calls shutdown(wait=True),
    # which would block until the worker finishes and defeat the timeout. We
    # shut down with wait=False and let the orphaned thread finish on its own.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(provider.generate, system, user, max_tokens)
        text = future.result(timeout=limit)
        text = (text or "").strip()
        if not text:
            logger.info("AI provider returned empty; falling back to raw text")
            return null.generate(system, user, max_tokens), False
        return text, True
    except concurrent.futures.TimeoutError:
        logger.warning("AI provider timed out after %ss; using raw text", limit)
        return null.generate(system, user, max_tokens), False
    except Exception as exc:  # noqa: BLE001 - never let AI break the flow
        logger.warning("AI provider failed (%s); using raw text", exc)
        return null.generate(system, user, max_tokens), False
    finally:
        pool.shutdown(wait=False)
