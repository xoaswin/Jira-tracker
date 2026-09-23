"""git <-> time reconciliation: catch forgotten logging.

Cross-references two things the app uniquely holds together over a time window:

* commits per ticket (from configured git repos, keyed by ABC-123 in the commit
  subject), and
* logged session time per ticket (completed sessions in the window).

and flags the mismatches:

* ``commits_no_time`` - you committed against a ticket but logged no time on it
  (the common "forgot to track" case),
* ``time_no_commits`` - you logged time but there are no commits (fine for
  non-code work; surfaced so you can sanity-check),
* ``ok`` - both present.

Local and deterministic. Degrades to just the time side when no repos are
configured (git contributes an empty map).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.git import commit_counts_by_issue_key
from app.models import WorkSession
from app.services.duration import effective_duration_seconds


@dataclass
class ReconcileRow:
    issue_key: str
    commit_count: int
    logged_seconds: int
    flag: str


def _session_seconds(s: WorkSession) -> int:
    if s.ended_at is None and s.adjusted_seconds is None:
        return 0
    return effective_duration_seconds(
        s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
    )


def reconcile(db: Session, start: datetime, end: datetime) -> list[ReconcileRow]:
    """Reconcile commits vs logged time per ticket in [start, end]."""
    repo_paths = get_settings().git_repo_paths
    commits = commit_counts_by_issue_key(
        repo_paths, start.isoformat(), end.isoformat()
    )

    # Logged seconds per ticket from completed sessions in the window.
    stmt = (
        select(WorkSession)
        .where(
            WorkSession.state == "completed",
            WorkSession.started_at >= start,
            WorkSession.started_at <= end,
            WorkSession.issue_key.is_not(None),
        )
    )
    logged: dict[str, int] = {}
    for s in db.execute(stmt).scalars().all():
        k = (s.issue_key or "").upper()
        if not k:
            continue
        logged[k] = logged.get(k, 0) + _session_seconds(s)

    rows: list[ReconcileRow] = []
    for key in set(commits) | set(logged):
        c = commits.get(key, 0)
        secs = logged.get(key, 0)
        if c > 0 and secs == 0:
            flag = "commits_no_time"
        elif c == 0 and secs > 0:
            flag = "time_no_commits"
        else:
            flag = "ok"
        rows.append(ReconcileRow(issue_key=key, commit_count=c, logged_seconds=secs, flag=flag))

    # Most actionable first: commits-no-time, then time-no-commits, then ok;
    # within a group, more commits / more time first.
    order = {"commits_no_time": 0, "time_no_commits": 1, "ok": 2}
    rows.sort(key=lambda r: (order.get(r.flag, 9), -(r.commit_count + r.logged_seconds)))
    return rows
