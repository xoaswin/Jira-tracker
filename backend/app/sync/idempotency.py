"""Idempotency checks run before every retry (section 5.8, read twice).

Jira worklog creation has no idempotency key. If a request times out but
actually succeeded server-side, a naive retry creates a duplicate worklog and
hours are silently wrong. Before any retry we look for a worklog already on
the issue that matches what we were about to send (same author, same
``started`` instant, same ``timeSpentSeconds``); if found we treat the outbox
item as done instead of sending it again. Comments get the analogous check,
matching on exact body text and author within a short time window, since
comments have no timestamp field to match exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.jira.adf import adf_to_text
from app.jira.client import JiraClient
from app.jira.comments import get_comments
from app.jira.datetime_fmt import parse_jira_datetime
from app.jira.worklogs import get_worklogs

COMMENT_MATCH_WINDOW = timedelta(minutes=10)


def find_existing_worklog(
    client: JiraClient,
    issue_key: str,
    account_id: str | None,
    started: datetime,
    time_spent_seconds: int,
) -> str | None:
    """Return the id of a worklog already on the issue matching this push, if any."""
    for wl in get_worklogs(client, issue_key):
        author = (wl.get("author") or {}).get("accountId")
        if account_id and author != account_id:
            continue
        if wl.get("timeSpentSeconds") != time_spent_seconds:
            continue
        wl_started = wl.get("started")
        if not wl_started:
            continue
        try:
            if parse_jira_datetime(wl_started) != _aware(started):
                continue
        except (ValueError, OverflowError):
            continue
        return str(wl.get("id"))
    return None


def find_recent_duplicate_worklog(
    client: JiraClient,
    issue_key: str,
    account_id: str | None,
    around: datetime,
    time_spent_seconds: int,
    comment_text: str | None,
    *,
    window: timedelta = timedelta(minutes=2),
) -> str | None:
    """Return a worklog id that looks like a duplicate of one about to be posted.

    Unlike :func:`find_existing_worklog` (which matches an exact ``started``
    instant for outbox retries), this guards the manual "Log work" button where
    each burst request computes its own ``now``. A match is: same author, same
    ``timeSpentSeconds``, same comment text, and ``started`` within ``window`` of
    ``around``. Two identical worklogs within two minutes are far more likely a
    duplicate submission than intentional, so we treat them as one.
    """
    target_comment = (comment_text or "").strip()
    for wl in get_worklogs(client, issue_key):
        author = (wl.get("author") or {}).get("accountId")
        if account_id and author != account_id:
            continue
        if wl.get("timeSpentSeconds") != time_spent_seconds:
            continue
        if adf_to_text(wl.get("comment")).strip() != target_comment:
            continue
        wl_started = wl.get("started")
        if not wl_started:
            continue
        try:
            if abs(parse_jira_datetime(wl_started) - _aware(around)) > window:
                continue
        except (ValueError, OverflowError):
            continue
        return str(wl.get("id"))
    return None


def find_existing_comment(
    client: JiraClient,
    issue_key: str,
    account_id: str | None,
    body_text: str,
    around: datetime,
) -> str | None:
    """Return the id of a comment already on the issue matching this push, if any."""
    for c in get_comments(client, issue_key):
        author = (c.get("author") or {}).get("accountId")
        if account_id and author != account_id:
            continue
        if adf_to_text(c.get("body")).strip() != body_text.strip():
            continue
        created = c.get("created")
        if created:
            try:
                if abs(parse_jira_datetime(created) - _aware(around)) > COMMENT_MATCH_WINDOW:
                    continue
            except (ValueError, OverflowError):
                pass
        return str(c.get("id"))
    return None


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
