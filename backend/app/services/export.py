"""Data export: SQLite backup and timesheet CSV.

The local SQLite DB is the source of truth for in-flight work, so a one-click
backup matters. The timesheet CSV is a portable record of completed, tracked
work over a range (for reporting or importing elsewhere).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Issue, WorkSession
from app.services.duration import effective_duration_seconds


def backup_db_path() -> str | None:
    """Absolute path to the SQLite DB file, or None for a non-file DB."""
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return None


def _session_seconds(s: WorkSession) -> int:
    if s.ended_at is None and s.adjusted_seconds is None:
        return 0
    return effective_duration_seconds(
        s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
    )


def timesheet_csv(db: Session, start: datetime, end: datetime) -> str:
    """A CSV of completed sessions in [start, end], one row per session."""
    types: dict[str, str | None] = dict(
        db.execute(select(Issue.issue_key, Issue.issue_type)).all()
    )

    stmt = (
        select(WorkSession)
        .where(
            WorkSession.state == "completed",
            WorkSession.started_at >= start,
            WorkSession.started_at <= end,
        )
        .order_by(WorkSession.started_at.asc())
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "date",
            "started_at_utc",
            "issue_key",
            "issue_type",
            "description",
            "hours",
            "seconds",
            "sync_state",
        ]
    )
    for s in db.execute(stmt).scalars().all():
        secs = _session_seconds(s)
        started = s.started_at.astimezone(timezone.utc)
        writer.writerow(
            [
                started.date().isoformat(),
                started.isoformat(),
                s.issue_key or "",
                types.get(s.issue_key or "", "") or "",
                (s.description or "").replace("\n", " ").strip(),
                round(secs / 3600, 2),
                secs,
                s.sync_state,
            ]
        )
    return buf.getvalue()
