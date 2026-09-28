"""End-of-day wrap-up: review today's sessions and log them to Jira in one go.

The desktop app shows this at work end (in the configured timezone). It lists
today's completed sessions with their sync state, drafts a worklog comment per
session from the git commits made on that ticket's branch, and logs every
not-yet-synced session through the same durable path as "finish session"
(``repush_session`` -> outbox), so nothing here can duplicate a worklog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkSession
from app.services.ai_text import draft_worklog_from_git
from app.services.connection import get_settings_row
from app.services.duration import effective_duration_seconds
from app.services.repush import repush_session
from app.services.tz import app_tz, day_bounds, today as local_today

ACTIVE_STATES = ("active", "paused")


@dataclass
class WrapupSession:
    id: int
    issue_key: str | None
    description: str
    notes: str | None
    seconds: int
    started_at: str
    ended_at: str | None
    sync_state: str
    sync_error: str | None


@dataclass
class WrapupDay:
    date: str
    tracked_seconds: int = 0
    logged_seconds: int = 0
    target_seconds: int = 0
    # A timer still running at wrap-up time; the card asks to stop it first.
    active_session_id: int | None = None
    active_issue_key: str | None = None
    sessions: list[WrapupSession] = field(default_factory=list)


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def today_wrapup(db: Session) -> WrapupDay:
    tz = app_tz(db)
    today = local_today(tz)
    start, end = day_bounds(today, today, tz)
    row = get_settings_row(db)
    target_hours = (row.daily_target_hours if row else 0) or 0

    day = WrapupDay(date=today.isoformat(), target_seconds=int(target_hours * 3600))

    stmt = (
        select(WorkSession)
        .where(
            WorkSession.state == "completed",
            WorkSession.started_at >= start,
            WorkSession.started_at <= end,
        )
        .order_by(WorkSession.started_at.asc())
    )
    for s in db.execute(stmt).scalars().all():
        secs = effective_duration_seconds(
            s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
        )
        day.tracked_seconds += secs
        if s.sync_state == "synced":
            day.logged_seconds += secs
        day.sessions.append(
            WrapupSession(
                id=s.id,
                issue_key=s.issue_key,
                description=s.description,
                notes=s.notes,
                seconds=secs,
                started_at=_iso(s.started_at),
                ended_at=_iso(s.ended_at),
                sync_state=s.sync_state,
                sync_error=s.sync_error,
            )
        )

    active = (
        db.execute(
            select(WorkSession)
            .where(WorkSession.state.in_(ACTIVE_STATES))
            .order_by(WorkSession.started_at.desc())
        )
        .scalars()
        .first()
    )
    if active:
        day.active_session_id = active.id
        day.active_issue_key = active.issue_key
    return day


@dataclass
class DraftComment:
    text: str
    used_ai: bool
    # "git" (from commits), "notes" (the session's own notes) or "none".
    source: str
    commit_count: int = 0


def draft_comment(db: Session, session: WorkSession) -> DraftComment:
    """A worklog comment for ``session``: git commits first, else its notes."""
    if session.issue_key:
        draft = draft_worklog_from_git(db, session.issue_key, _iso(session.started_at))
        if draft.text:
            return DraftComment(
                text=draft.text,
                used_ai=draft.used_ai,
                source="git",
                commit_count=draft.commit_count,
            )
    if session.notes:
        return DraftComment(text=session.notes, used_ai=False, source="notes")
    return DraftComment(text="", used_ai=False, source="none")


@dataclass
class LogOutcome:
    session_id: int
    ok: bool
    sync_state: str | None
    message: str


def log_sessions(db: Session, items: list[dict]) -> list[LogOutcome]:
    """Apply edits and push each session. Already-synced sessions are updated in
    place only when their comment changed; otherwise they are left alone."""
    out: list[LogOutcome] = []
    for item in items:
        sid = int(item["session_id"])
        s = db.get(WorkSession, sid)
        if s is None or s.state != "completed":
            out.append(LogOutcome(sid, False, None, "Session not found or still running."))
            continue

        notes = item.get("notes")
        notes_changed = notes is not None and notes != (s.notes or "")
        if notes_changed:
            s.notes = notes

        key = (item.get("issue_key") or "").strip().upper() or None
        if key and key != s.issue_key:
            if s.sync_state == "synced":
                # Moving a logged worklog between tickets isn't supported here.
                db.commit()
                out.append(LogOutcome(sid, False, s.sync_state,
                                      "Already logged; change its ticket from the dashboard."))
                continue
            s.issue_key = key
        db.commit()

        if s.sync_state == "synced" and not notes_changed:
            out.append(LogOutcome(sid, True, "synced", "Already logged."))
            continue
        if not s.issue_key:
            out.append(LogOutcome(sid, False, s.sync_state, "No ticket; pick one to log it."))
            continue

        result = repush_session(db, s)
        db.refresh(s)
        # Pending = durably queued in the outbox, which is fine at day end.
        ok = s.sync_state in ("synced", "pending")
        if s.sync_state == "synced":
            msg = "Updated in Jira." if result.get("status") == "updated" else "Logged to Jira."
        elif s.sync_state == "pending":
            msg = s.sync_error or "Queued; will sync when Jira is reachable."
        else:
            msg = s.sync_error or "Could not log to Jira."
        out.append(LogOutcome(sid, ok, s.sync_state, msg))
    return out
