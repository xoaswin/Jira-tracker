"""Reporting: tracked vs logged hours, and unlogged sessions (section 10, 11).

* Weekly report: for each day in the week, the tracked seconds (all completed
  sessions) versus the successfully-logged seconds (sessions whose sync_state is
  "synced"), plus a per-issue breakdown.
* Unlogged: completed sessions with no successful Jira push, which the dashboard
  surfaces as needing attention (rule 2: never lose a session).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkSession
from app.services.duration import effective_duration_seconds


@dataclass
class DayBucket:
    day: str  # ISO date
    tracked_seconds: int = 0
    logged_seconds: int = 0


@dataclass
class IssueBucket:
    issue_key: str | None
    tracked_seconds: int = 0
    logged_seconds: int = 0


@dataclass
class WeekReport:
    week_start: str
    week_end: str
    total_tracked_seconds: int = 0
    total_logged_seconds: int = 0
    days: list[DayBucket] = field(default_factory=list)
    issues: list[IssueBucket] = field(default_factory=list)


def _week_bounds(anchor: date) -> tuple[date, date]:
    """Monday..Sunday containing ``anchor``."""
    monday = anchor - timedelta(days=anchor.weekday())
    return monday, monday + timedelta(days=6)


def _session_seconds(s: WorkSession) -> int:
    if s.ended_at is None and s.adjusted_seconds is None:
        return 0
    return effective_duration_seconds(
        s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
    )


def week_report(db: Session, anchor: date | None = None) -> WeekReport:
    """Build the tracked-vs-logged report for the week containing ``anchor``."""
    anchor = anchor or datetime.now(timezone.utc).date()
    monday, sunday = _week_bounds(anchor)
    start_dt = datetime.combine(monday, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(sunday, time.max, tzinfo=timezone.utc)

    stmt = (
        select(WorkSession)
        .where(
            WorkSession.state == "completed",
            WorkSession.started_at >= start_dt,
            WorkSession.started_at <= end_dt,
        )
        .order_by(WorkSession.started_at.asc())
    )
    sessions = list(db.execute(stmt).scalars().all())

    days: dict[str, DayBucket] = {
        (monday + timedelta(days=i)).isoformat(): DayBucket(
            day=(monday + timedelta(days=i)).isoformat()
        )
        for i in range(7)
    }
    issues: dict[str | None, IssueBucket] = {}
    total_tracked = 0
    total_logged = 0

    for s in sessions:
        secs = _session_seconds(s)
        logged = secs if s.sync_state == "synced" else 0
        total_tracked += secs
        total_logged += logged

        day_key = s.started_at.astimezone(timezone.utc).date().isoformat()
        bucket = days.get(day_key)
        if bucket is not None:
            bucket.tracked_seconds += secs
            bucket.logged_seconds += logged

        ib = issues.setdefault(s.issue_key, IssueBucket(issue_key=s.issue_key))
        ib.tracked_seconds += secs
        ib.logged_seconds += logged

    return WeekReport(
        week_start=monday.isoformat(),
        week_end=sunday.isoformat(),
        total_tracked_seconds=total_tracked,
        total_logged_seconds=total_logged,
        days=list(days.values()),
        issues=sorted(issues.values(), key=lambda i: i.tracked_seconds, reverse=True),
    )


def unlogged_sessions(db: Session) -> list[WorkSession]:
    """Completed sessions that have not successfully synced to Jira (section 10).

    These are the ones the dashboard flags as needing attention: an error, or
    still pending/unsynced despite being completed.
    """
    stmt = (
        select(WorkSession)
        .where(
            WorkSession.state == "completed",
            WorkSession.sync_state != "synced",
        )
        .order_by(WorkSession.ended_at.desc().nullslast())
    )
    return list(db.execute(stmt).scalars().all())
