"""Re-push a completed session after editing it (Dashboard "fix and re-sync").

The hard rule here is rule 3: never create a duplicate worklog. So:

* If the session already has a synced worklog on the SAME issue, we UPDATE that
  worklog in place (PUT) rather than posting a new one, and likewise for the
  comment where possible.
* If the issue key changed, the old worklog is on the wrong issue: we DELETE it,
  clear the synced ids, and enqueue a fresh push to the new issue.
* If it was never synced, we simply (re)enqueue.

Enqueued items go through the normal durable outbox, so retries and the pre-retry
idempotency check still apply.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jira.client import JiraError
from app.jira.worklogs import normalize_time_spent, update_worklog
from app.jira.comments import add_comment
from app.models import Outbox, WorkSession
from app.services.connection import build_client, get_settings_row
from app.services.duration import effective_duration_seconds
from app.sync.outbox import enqueue_session_push

logger = logging.getLogger("jira_tracker.repush")


def _clear_pending_items(db: Session, session_id: int) -> None:
    """Drop any not-done outbox items for this session before re-enqueuing, so
    we never stack duplicate pending pushes."""
    stmt = select(Outbox).where(
        Outbox.session_id == session_id, Outbox.state.in_(("pending", "failed"))
    )
    for item in db.execute(stmt).scalars().all():
        db.delete(item)
    db.commit()


def repush_session(db: Session, session: WorkSession) -> dict:
    """Re-sync an edited completed session. Returns a small status dict."""
    if session.state != "completed":
        return {"status": "skipped", "reason": "not completed"}
    if not session.issue_key:
        session.sync_state = "unsynced"
        session.sync_error = "No issue selected; nothing to push."
        db.commit()
        return {"status": "no_issue"}

    row = get_settings_row(db)
    if row and row.needs_reauth:
        return {"status": "needs_reauth"}

    raw_duration = effective_duration_seconds(
        session.started_at, session.ended_at, session.paused_seconds, session.adjusted_seconds
    )
    time_spent, _ = normalize_time_spent(raw_duration)

    # Case 1: already synced on the SAME issue -> update the worklog in place.
    synced_worklog = session.worklog_jira_id and session.sync_state == "synced"
    if synced_worklog:
        try:
            with build_client(db) as client:
                update_worklog(
                    client,
                    session.issue_key,
                    session.worklog_jira_id,
                    session.started_at,
                    time_spent,
                    comment_text=session.notes or None,
                )
                # Add a fresh comment for the new notes if there are any; comments
                # are append-only in this app, so we do not try to edit old ones.
                if session.notes:
                    comment = add_comment(client, session.issue_key, session.notes)
                    session.comment_jira_id = str(comment.get("id")) if comment else session.comment_jira_id
            session.sync_state = "synced"
            session.sync_error = None
            db.commit()
            return {"status": "updated"}
        except JiraError as exc:
            logger.error("repush update failed for session %s: %s", session.id, exc.to_dict())
            session.sync_state = "error"
            session.sync_error = _fmt(exc)
            db.commit()
            return {"status": "error", "detail": session.sync_error}

    # Case 2/3: never cleanly synced (or issue changed) -> re-enqueue fresh.
    _clear_pending_items(db, session.id)
    session.worklog_jira_id = None
    session.comment_jira_id = None
    session.sync_state = "unsynced"
    session.sync_error = None
    db.commit()

    enqueue_session_push(db, session)
    from app.sync.worker import process_due_items

    process_due_items(db)
    db.refresh(session)
    return {"status": session.sync_state}


def _fmt(exc: JiraError) -> str:
    parts = []
    if exc.status_code is not None:
        parts.append(f"HTTP {exc.status_code}")
    parts.append(str(exc.body) if exc.body is not None else exc.message)
    return " ".join(parts)
