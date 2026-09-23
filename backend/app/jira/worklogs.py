"""Worklog creation and reading (section 5.4, section 5.8).

The ``started`` field must be in Jira's exact format (see datetime_fmt). We send
``timeSpentSeconds`` as an integer and never send ``timeSpent`` alongside it.
Jira's minimum granularity is 60 seconds, so anything shorter is rounded up and
the caller is told it was rounded.
"""

from __future__ import annotations

from datetime import datetime

from app.jira.adf import text_to_adf
from app.jira.client import JiraClient
from app.jira.datetime_fmt import jira_datetime

MIN_WORKLOG_SECONDS = 60


def normalize_time_spent(seconds: int) -> tuple[int, bool]:
    """Return (seconds_to_send, was_rounded_up).

    Jira rejects worklogs under 60 seconds, so round those up and flag it so the
    UI can warn (section 5.4).
    """
    if seconds < MIN_WORKLOG_SECONDS:
        return MIN_WORKLOG_SECONDS, True
    return int(seconds), False


def build_worklog_payload(
    started: datetime, time_spent_seconds: int, comment_text: str | None = None
) -> dict:
    """Build the worklog POST body. The ``comment`` field is ADF."""
    seconds, _ = normalize_time_spent(time_spent_seconds)
    payload: dict = {
        "started": jira_datetime(started),
        "timeSpentSeconds": seconds,
    }
    if comment_text:
        payload["comment"] = text_to_adf(comment_text)
    return payload


def add_worklog(
    client: JiraClient,
    issue_key: str,
    started: datetime,
    time_spent_seconds: int,
    comment_text: str | None = None,
) -> dict:
    """POST /rest/api/3/issue/{key}/worklog -> the created worklog (has ``id``)."""
    payload = build_worklog_payload(started, time_spent_seconds, comment_text)
    return client.post(f"/rest/api/3/issue/{issue_key}/worklog", json_body=payload)


def get_worklogs(client: JiraClient, issue_key: str) -> list[dict]:
    """GET all worklogs on an issue (used by the Phase 2 idempotency check)."""
    result = client.get(f"/rest/api/3/issue/{issue_key}/worklog")
    return result.get("worklogs", []) if isinstance(result, dict) else []


def update_worklog(
    client: JiraClient,
    issue_key: str,
    worklog_id: str,
    started: datetime,
    time_spent_seconds: int,
    comment_text: str | None = None,
) -> dict:
    """PUT an existing worklog in place, so editing a synced session does not
    create a duplicate (rule 3)."""
    payload = build_worklog_payload(started, time_spent_seconds, comment_text)
    return client.request(
        "PUT",
        f"/rest/api/3/issue/{issue_key}/worklog/{worklog_id}",
        json_body=payload,
    )


def delete_worklog(client: JiraClient, issue_key: str, worklog_id: str) -> None:
    """DELETE a worklog (used when a re-push moves work to a different issue)."""
    client.request("DELETE", f"/rest/api/3/issue/{issue_key}/worklog/{worklog_id}")
