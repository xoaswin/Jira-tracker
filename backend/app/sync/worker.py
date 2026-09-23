"""The outbox worker: turns pending rows into real Jira writes (Phase 2).

Retry policy (section 5.7):
  * Retry on 429, 500, 502, 503, 504, and on connection/timeout errors.
  * Never retry on 400, 401, 403, 404 for the *payload* those are permanent.
    401 is special: the token itself is dead, so instead of failing the item
    we leave it pending, flag ``needs_reauth`` on settings, and stop this pass
    entirely so we don't burn the backoff schedule against a dead token.
  * Exponential backoff with jitter (``app.sync.backoff``), or the exact
    ``Retry-After`` value when Jira sends one.

Idempotency (section 5.8): before any retry (attempts > 0) of a worklog or
comment push, check Jira for a matching item already created by a prior
attempt that timed out client-side but actually landed server-side. If found,
treat the outbox item as done instead of sending again.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jira.client import JiraClient, JiraError
from app.jira.comments import add_comment
from app.jira.transitions import transition_issue
from app.jira.worklogs import add_worklog
from app.models import Outbox, WorkSession, utcnow
from app.services.connection import NotConnectedError, build_client, get_settings_row
from app.sync.backoff import next_attempt_time
from app.sync.idempotency import find_existing_comment, find_existing_worklog

logger = logging.getLogger("jira_tracker.outbox_worker")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ReauthRequired(Exception):
    """Raised to stop a worker pass early after a 401 (section 5.7)."""


def _format_error(exc: JiraError) -> str:
    parts = []
    if exc.status_code is not None:
        parts.append(f"HTTP {exc.status_code}")
    parts.append(str(exc.body) if exc.body is not None else exc.message)
    return " ".join(parts)


def _is_retryable(exc: JiraError) -> bool:
    if exc.status_code is None:
        return True  # transport-level: timeout or connection error
    return exc.status_code in RETRYABLE_STATUS_CODES


def _apply_failure(db: Session, item: Outbox, exc: JiraError) -> None:
    if exc.status_code == 401:
        item.last_error = _format_error(exc)
        # Leave pending and due now; do not push it into the backoff future,
        # so it fires again immediately once the user reconnects.
        item.next_attempt_at = utcnow()
        item.state = "pending"
        db.commit()
        raise ReauthRequired()

    if _is_retryable(exc):
        item.last_error = _format_error(exc)
        item.next_attempt_at = next_attempt_time(item.attempts, retry_after=exc.retry_after)
        item.state = "pending"
    else:
        item.state = "failed"
        item.last_error = _format_error(exc)
    db.commit()


def _mark_done(db: Session, item: Outbox, jira_result_id: str | None) -> None:
    item.state = "done"
    item.jira_result_id = jira_result_id
    item.last_error = None
    item.completed_at = utcnow()
    db.commit()


def _process_worklog(db: Session, client: JiraClient, item: Outbox, account_id: str | None) -> None:
    payload = item.payload
    issue_key = payload["issue_key"]
    started = datetime.fromisoformat(payload["started"])
    time_spent = payload["time_spent_seconds"]
    comment_text = payload.get("comment_text")

    if item.attempts > 0:
        existing = find_existing_worklog(client, issue_key, account_id, started, time_spent)
        if existing:
            _mark_done(db, item, existing)
            return

    item.attempts += 1
    db.commit()
    try:
        worklog = add_worklog(client, issue_key, started, time_spent, comment_text)
        _mark_done(db, item, str(worklog.get("id")) if worklog else None)
    except JiraError as exc:
        logger.error("worklog push failed for outbox %s: %s", item.id, exc.to_dict())
        _apply_failure(db, item, exc)


def _process_comment(db: Session, client: JiraClient, item: Outbox, account_id: str | None) -> None:
    payload = item.payload
    issue_key = payload["issue_key"]
    body_text = payload["body_text"]
    around = datetime.fromisoformat(payload["around"])

    if item.attempts > 0:
        existing = find_existing_comment(client, issue_key, account_id, body_text, around)
        if existing:
            _mark_done(db, item, existing)
            return

    item.attempts += 1
    db.commit()
    try:
        comment = add_comment(client, issue_key, body_text)
        _mark_done(db, item, str(comment.get("id")) if comment else None)
    except JiraError as exc:
        logger.error("comment push failed for outbox %s: %s", item.id, exc.to_dict())
        _apply_failure(db, item, exc)


def _process_transition(db: Session, client: JiraClient, item: Outbox) -> None:
    payload = item.payload
    issue_key = payload["issue_key"]
    target_name = payload["target_name"]

    item.attempts += 1
    db.commit()
    try:
        # A missing transition is not an error (section 5.6): mark done either
        # way. transition_issue returns False when it skipped silently.
        performed = transition_issue(client, issue_key, target_name)
        note = None if performed else f"No transition named {target_name!r}; skipped."
        _mark_done(db, item, None)
        if note:
            logger.info("outbox %s: %s", item.id, note)
    except JiraError as exc:
        logger.error("transition failed for outbox %s: %s", item.id, exc.to_dict())
        _apply_failure(db, item, exc)


def process_item(db: Session, client: JiraClient, item: Outbox, account_id: str | None) -> None:
    if item.kind == "worklog":
        _process_worklog(db, client, item, account_id)
    elif item.kind == "comment":
        _process_comment(db, client, item, account_id)
    elif item.kind == "transition":
        _process_transition(db, client, item)
    else:
        item.state = "failed"
        item.last_error = f"Unsupported outbox kind: {item.kind}"
        db.commit()


def update_session_sync_state(db: Session, session_id: int) -> None:
    """Recompute a session's sync_state/sync_error from its outbox items.

    Also mirrors each item's ``jira_result_id`` back onto the session's
    ``worklog_jira_id`` / ``comment_jira_id`` columns so the existing session
    views keep showing the Jira ids without needing to join the outbox.
    """
    session = db.get(WorkSession, session_id)
    if session is None:
        return
    items = list(
        db.execute(select(Outbox).where(Outbox.session_id == session_id)).scalars().all()
    )
    if not items:
        return

    for i in items:
        if i.jira_result_id:
            if i.kind == "worklog":
                session.worklog_jira_id = i.jira_result_id
            elif i.kind == "comment":
                session.comment_jira_id = i.jira_result_id

    if all(i.state == "done" for i in items):
        session.sync_state = "synced"
        session.sync_error = None
    elif any(i.state == "failed" for i in items):
        session.sync_state = "error"
        failed = next(i for i in items if i.state == "failed")
        session.sync_error = failed.last_error
    else:
        session.sync_state = "unsynced"
        with_error = next((i for i in items if i.last_error), None)
        session.sync_error = with_error.last_error if with_error else None
    db.commit()


def process_due_items(db: Session, *, limit: int = 50) -> dict:
    """Process all pending outbox items whose next_attempt_at has arrived.

    Returns a small status dict for callers (API responses, logging).
    """
    row = get_settings_row(db)
    if row and row.needs_reauth:
        return {"processed": 0, "reason": "needs_reauth"}

    try:
        client = build_client(db)
    except NotConnectedError:
        return {"processed": 0, "reason": "not_connected"}

    account_id = row.account_id if row else None
    processed = 0
    touched_sessions: set[int] = set()
    reauth_hit = False
    try:
        stmt = (
            select(Outbox)
            .where(Outbox.state == "pending", Outbox.next_attempt_at <= utcnow())
            .order_by(Outbox.next_attempt_at.asc())
            .limit(limit)
        )
        due = list(db.execute(stmt).scalars().all())
        for item in due:
            try:
                process_item(db, client, item, account_id)
            except ReauthRequired:
                if row is not None:
                    row.needs_reauth = True
                    db.commit()
                reauth_hit = True
                if item.session_id:
                    touched_sessions.add(item.session_id)
                break
            processed += 1
            if item.session_id:
                touched_sessions.add(item.session_id)
    finally:
        client.close()

    for sid in touched_sessions:
        update_session_sync_state(db, sid)

    return {"processed": processed, "reason": "needs_reauth" if reauth_hit else None}
