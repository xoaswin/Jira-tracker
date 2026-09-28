"""Safe multi-turn chat with tool-calling for the assistant (section 8).

Mirrors ``factory.safe_generate``'s guarantees for the conversational assistant:
a hard wall-clock timeout enforced in a worker thread, and a silent fallback
(``used_ai=False`` with empty result) on ANY failure - timeout, network,
provider error, or a provider that has no ``chat`` capability at all. Never
raises, so the assistant endpoint can always return a graceful message.

Only providers that implement ``chat`` (currently Groq) support the assistant;
others degrade to the "configure an AI provider" message rather than crashing.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.ai.null import NullProvider

logger = logging.getLogger("jira_tracker.ai.chat")

# The assistant does more than tweak wording, so it gets a longer cap than the
# 10s worklog-path default; still bounded so the UI never hangs.
CHAT_TIMEOUT_SECONDS = 30.0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The raw assistant message (with tool_calls), echoed back into the messages
    # array during the agentic loop before appending each tool's result.
    raw_message: dict | None = None
    used_ai: bool = False


def safe_chat(
    db: Session,
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    max_tokens: int = 700,
    timeout: float | None = None,
) -> ChatResult:
    """Run the configured provider's ``chat`` with a timeout + safe fallback."""
    provider = get_provider(db)
    chat_fn = getattr(provider, "chat", None)
    if isinstance(provider, NullProvider) or chat_fn is None:
        # No chat-capable provider configured; caller shows a "set up AI" hint.
        return ChatResult(used_ai=False)

    limit = timeout if timeout is not None else CHAT_TIMEOUT_SECONDS
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(chat_fn, messages, tools, max_tokens)
        raw = future.result(timeout=limit)
        text = (raw.get("content") or "").strip()
        calls: list[ToolCall] = []
        for tc in raw.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            if not name:
                continue
            args_raw = fn.get("arguments")
            if isinstance(args_raw, str):
                try:
                    args = json.loads(args_raw or "{}")
                except (ValueError, TypeError):
                    args = {}
            elif isinstance(args_raw, dict):
                args = args_raw
            else:
                args = {}
            calls.append(ToolCall(id=tc.get("id") or "", name=name, arguments=args))
        return ChatResult(text=text, tool_calls=calls, raw_message=raw, used_ai=True)
    except concurrent.futures.TimeoutError:
        logger.warning("assistant chat timed out after %ss", limit)
        return ChatResult(used_ai=False)
    except Exception as exc:  # noqa: BLE001 - never let AI break the flow
        logger.warning("assistant chat failed (%s)", exc)
        return ChatResult(used_ai=False)
    finally:
        pool.shutdown(wait=False)
