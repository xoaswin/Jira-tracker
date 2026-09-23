"""Insights: turn accumulated sessions into "where my time goes" analytics.

Aggregates completed sessions over an arbitrary range into the breakdowns the
Insights screen renders: totals, tracked-vs-logged, by project, by issue type,
by ticket, and a per-day trend. All local and deterministic; no Jira calls.

Issue type/project come from the cached `issues` rows joined by issue_key (the
session itself only stores the key). Sessions whose issue is not cached still
count toward totals and per-day, grouped as an "untyped"/"no project" bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Issue, WorkSession
from app.services.duration import effective_duration_seconds


@dataclass
class Bucket:
    key: str  # project key / issue type / issue key / ISO day
    label: str
    tracked_seconds: int = 0
    logged_seconds: int = 0
    session_count: int = 0


@dataclass
class Insights:
    range_start: str
    range_end: str
    total_tracked_seconds: int = 0
    total_logged_seconds: int = 0
    session_count: int = 0
    ticket_count: int = 0
    by_project: list[Bucket] = field(default_factory=list)
    by_type: list[Bucket] = field(default_factory=list)
    by_ticket: list[Bucket] = field(default_factory=list)
    by_day: list[Bucket] = field(default_factory=list)


def _session_seconds(s: WorkSession) -> int:
    if s.ended_at is None and s.adjusted_seconds is None:
        return 0
    return effective_duration_seconds(
        s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
    )


def _bump(index: dict[str, Bucket], key: str, label: str, secs: int, logged: int) -> None:
    b = index.get(key)
    if b is None:
        b = Bucket(key=key, label=label)
        index[key] = b
    b.tracked_seconds += secs
    b.logged_seconds += logged
    b.session_count += 1


def compute_insights(
    db: Session, start: datetime, end: datetime
) -> Insights:
    """Aggregate completed sessions in [start, end] into breakdowns."""
    # issue_key -> (project_key, issue_type) from the cache.
    meta: dict[str, tuple[str | None, str | None]] = {
        key: (proj, itype)
        for key, proj, itype in db.execute(
            select(Issue.issue_key, Issue.project_key, Issue.issue_type)
        ).all()
    }

    stmt = (
        select(WorkSession)
        .where(
            WorkSession.state == "completed",
            WorkSession.started_at >= start,
            WorkSession.started_at <= end,
        )
        .order_by(WorkSession.started_at.asc())
    )
    sessions = list(db.execute(stmt).scalars().all())

    by_project: dict[str, Bucket] = {}
    by_type: dict[str, Bucket] = {}
    by_ticket: dict[str, Bucket] = {}
    by_day: dict[str, Bucket] = {}

    total_tracked = 0
    total_logged = 0
    for s in sessions:
        secs = _session_seconds(s)
        logged = secs if s.sync_state == "synced" else 0
        total_tracked += secs
        total_logged += logged

        key = s.issue_key
        proj, itype = meta.get(key or "", (None, None))
        # Derive project from the key prefix when the issue is not cached.
        if not proj and key and "-" in key:
            proj = key.rsplit("-", 1)[0]

        _bump(by_project, proj or "(none)", proj or "No project", secs, logged)
        _bump(by_type, itype or "(untyped)", itype or "Untyped", secs, logged)
        if key:
            _bump(by_ticket, key, key, secs, logged)
        else:
            _bump(by_ticket, "(no ticket)", "No ticket", secs, logged)

        day = s.started_at.astimezone(timezone.utc).date().isoformat()
        _bump(by_day, day, day, secs, logged)

    def _sorted(d: dict[str, Bucket], limit: int | None = None) -> list[Bucket]:
        items = sorted(d.values(), key=lambda b: b.tracked_seconds, reverse=True)
        return items[:limit] if limit else items

    return Insights(
        range_start=start.date().isoformat(),
        range_end=end.date().isoformat(),
        total_tracked_seconds=total_tracked,
        total_logged_seconds=total_logged,
        session_count=len(sessions),
        ticket_count=len([k for k in by_ticket if k != "(no ticket)"]),
        by_project=_sorted(by_project),
        by_type=_sorted(by_type),
        by_ticket=_sorted(by_ticket, limit=10),
        # Days in chronological order for a trend line, not by size.
        by_day=sorted(by_day.values(), key=lambda b: b.key),
    )


def range_from_preset(preset: str, anchor: date | None = None) -> tuple[datetime, datetime]:
    """Resolve a preset ('week' | 'last_week' | 'month' | '30d') to UTC bounds."""
    anchor = anchor or datetime.now(timezone.utc).date()

    def day_bounds(a: date, b: date) -> tuple[datetime, datetime]:
        return (
            datetime.combine(a, time.min, tzinfo=timezone.utc),
            datetime.combine(b, time.max, tzinfo=timezone.utc),
        )

    if preset == "last_week":
        monday = anchor - timedelta(days=anchor.weekday() + 7)
        return day_bounds(monday, monday + timedelta(days=6))
    if preset == "month":
        first = anchor.replace(day=1)
        return day_bounds(first, anchor)
    if preset == "30d":
        return day_bounds(anchor - timedelta(days=29), anchor)
    # default "week": Monday..today of the current week
    monday = anchor - timedelta(days=anchor.weekday())
    return day_bounds(monday, anchor)
