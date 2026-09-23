"""Phase 1 direct synchronous push of a completed session to Jira.

Pushes a worklog (and, if there are notes, a comment) to the session's issue.
On failure the session is NOT lost: it stays completed with sync_state="error"
and the real Jira response body preserved in sync_error (rules 2 and 8). Phase 2
replaces this direct push with the durable outbox.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.jira.client import JiraClient, JiraError
from app.jira.comments import add_comment
from app.jira.worklogs import add_worklog, normalize_time_spent
from app.models import WorkSession
from app.services.duration import effective_duration_seconds

logger = logging.getLogger("jira_tracker.push")


class PushOutcome:
    def __init__(self, *, ok: bool, duration_seconds: int, rounded_up: bool, warning: str | None):
        self.ok = ok
        self.duration_seconds = duration_seconds
        self.rounded_up = rounded_up
        self.warning = warning


def push_session(db: Session, client: JiraClient, session: WorkSession) -> PushOutcome:
    """Push worklog + optional comment for a completed session."""
    raw_duration = effective_duration_seconds(
        session.started_at, session.ended_at, session.paused_seconds, session.adjusted_seconds
    )
    time_spent, rounded_up = normalize_time_spent(raw_duration)

    if not session.issue_key:
        # Nothing to push against; leave unsynced and warn.
        session.sync_state = "unsynced"
        session.sync_error = "No issue selected; nothing was pushed to Jira."
        db.commit()
        return PushOutcome(
            ok=False,
            duration_seconds=time_spent,
            rounded_up=rounded_up,
            warning="No issue selected, so no worklog was pushed.",
        )

    try:
        worklog = add_worklog(
            client,
            session.issue_key,
            session.started_at,
            time_spent,
            comment_text=session.notes or None,
        )
        session.worklog_jira_id = str(worklog.get("id")) if worklog else None

        if session.notes:
            comment = add_comment(client, session.issue_key, session.notes)
            session.comment_jira_id = str(comment.get("id")) if comment else None

        session.sync_state = "synced"
        session.sync_error = None
        db.commit()
        warning = (
            "Session was under a minute, so it was rounded up to 60 seconds."
            if rounded_up
            else None
        )
        return PushOutcome(ok=True, duration_seconds=time_spent, rounded_up=rounded_up, warning=warning)

    except JiraError as exc:
        logger.error("push failed for session %s: %s", session.id, exc.to_dict())
        session.sync_state = "error"
        session.sync_error = _format_error(exc)
        db.commit()
        return PushOutcome(
            ok=False,
            duration_seconds=time_spent,
            rounded_up=rounded_up,
            warning=f"Push to Jira failed: {session.sync_error}",
        )


def _format_error(exc: JiraError) -> str:
    parts = []
    if exc.status_code is not None:
        parts.append(f"HTTP {exc.status_code}")
    if exc.body is not None:
        parts.append(str(exc.body))
    else:
        parts.append(exc.message)
    return " ".join(parts)
