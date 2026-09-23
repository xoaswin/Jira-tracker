"""Reports and AI-text routes (Phase 5, section 10).

    GET  /api/reports/week?week=YYYY-MM-DD  -> tracked vs logged, per day/issue
    GET  /api/reports/unlogged              -> completed sessions not yet synced
    GET  /api/reports/daily-summary         -> AI standup summary (degrades)

    GET  /api/ai/status                     -> configured provider + availability
    POST /api/ai/cleanup-comment { text }   -> tidy a worklog comment (degrades)
    POST /api/ai/draft-summary   { text }   -> AI issue draft text (degrades)

The AI routes never block longer than the 10s provider timeout and always return
usable text with a ``used_ai`` flag (section 8).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.ai.null import NullProvider
from app.db import get_db
from app.schemas import (
    AIStatusOut,
    AITextRequest,
    AITextResponse,
    DraftWorklogRequest,
    DraftWorklogResponse,
    SessionOut,
    WeekReportOut,
)
from app.services.ai_text import cleanup_comment, daily_summary, draft_worklog_from_git
from app.services.reports import unlogged_sessions, week_report

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports/week", response_model=WeekReportOut)
def get_week_report(
    week: date | None = Query(None), db: Session = Depends(get_db)
) -> WeekReportOut:
    report = week_report(db, week)
    return WeekReportOut(
        week_start=report.week_start,
        week_end=report.week_end,
        total_tracked_seconds=report.total_tracked_seconds,
        total_logged_seconds=report.total_logged_seconds,
        days=[d.__dict__ for d in report.days],
        issues=[i.__dict__ for i in report.issues],
    )


@router.get("/reports/unlogged", response_model=list[SessionOut])
def get_unlogged(db: Session = Depends(get_db)) -> list[SessionOut]:
    # Reuse the sessions serialiser so elapsed_seconds is populated.
    from app.routers.sessions import _to_out

    return [_to_out(s) for s in unlogged_sessions(db)]


@router.get("/reports/daily-summary", response_model=AITextResponse)
def get_daily_summary(db: Session = Depends(get_db)) -> AITextResponse:
    text, used = daily_summary(db)
    return AITextResponse(text=text, used_ai=used)


@router.get("/ai/status", response_model=AIStatusOut)
def ai_status(db: Session = Depends(get_db)) -> AIStatusOut:
    provider = get_provider(db)
    if isinstance(provider, NullProvider):
        return AIStatusOut(provider="none", available=False)
    return AIStatusOut(
        provider=getattr(provider, "name", "unknown"),
        available=bool(provider.is_available()),
    )


@router.post("/ai/cleanup-comment", response_model=AITextResponse)
def ai_cleanup_comment(req: AITextRequest, db: Session = Depends(get_db)) -> AITextResponse:
    text, used = cleanup_comment(db, req.text)
    return AITextResponse(text=text, used_ai=used)


@router.post("/ai/draft-worklog", response_model=DraftWorklogResponse)
def ai_draft_worklog(
    req: DraftWorklogRequest, db: Session = Depends(get_db)
) -> DraftWorklogResponse:
    """Draft a worklog comment from git commits on the ticket's repo since the
    session started. Read-only and degrades cleanly (see the service)."""
    draft = draft_worklog_from_git(db, req.issue_key, req.since)
    return DraftWorklogResponse(
        text=draft.text,
        used_ai=draft.used_ai,
        commit_count=draft.commit_count,
        repo_found=draft.repo_path is not None,
    )


@router.post("/ai/draft-summary", response_model=AITextResponse)
def ai_draft_summary(req: AITextRequest, db: Session = Depends(get_db)) -> AITextResponse:
    from app.services.drafting import _draft_text_ai

    summary, description, used_ai = _draft_text_ai(db, req.text)
    # Return "summary\n\ndescription" so the UI can split if it wants both.
    return AITextResponse(text=f"{summary}\n\n{description}", used_ai=used_ai)