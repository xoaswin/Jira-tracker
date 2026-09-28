"""Contextual assistant route.

    POST /api/assistant/chat -> a chat reply grounded in the user's data, with
                                an optional confirm-gated ProposedAction.

The heavy lifting (context snapshot, tool-calling, safe fallback) lives in
``app.services.assistant``; this is a thin transport layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    AssistantActRequest,
    AssistantActResult,
    AssistantChatRequest,
    AssistantChatResponse,
)
from app.services.assistant import execute_action, run_chat

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
def chat_route(
    req: AssistantChatRequest, db: Session = Depends(get_db)
) -> AssistantChatResponse:
    return run_chat(db, req)


@router.post("/act", response_model=AssistantActResult)
def act_route(
    req: AssistantActRequest, db: Session = Depends(get_db)
) -> AssistantActResult:
    """Execute a confirmed ProposedAction server-side (the web + desktop clients
    both call this after the user clicks Confirm)."""
    r = execute_action(db, req.type, req.args, req.local_date)
    return AssistantActResult(
        ok=bool(r.get("ok")), message=str(r.get("message") or ""), session_id=r.get("session_id")
    )
