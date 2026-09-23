"""Auto-stamp a ticket's actual start/end dates from a work session.

When the ``auto_actual_dates`` setting is on, finishing (or manually logging) a
session best-effort writes the ticket's "actual start" and "actual end" date
fields so the user never hand-edits them:

* actual start: set to the session start, but only if the field is currently
  empty (the first session on a ticket wins; later sessions do not clobber it).
* actual end: set to the session end (always advanced to the latest work).

The field ids are instance-specific, so we discover them from editmeta and match
by name (Jira has no canonical id for these custom fields). Everything is
best-effort and never raises: if the fields are absent or Jira rejects the
write, we log and move on. AI-free, Jira-only.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.jira.client import JiraClient, JiraError
from app.jira.editmeta import get_editable_date_fields, update_issue_fields

logger = logging.getLogger("jira_tracker.auto_dates")

# Name fragments (lowercased) that identify the two fields. Jira instances name
# these variously ("Start date", "Actual start", "Actual start date", ...).
_START_HINTS = ("actual start", "start date", "start")
_END_HINTS = ("actual end", "end date", "actual finish", "finish", "end")


def _match(fields, hints) -> str | None:
    """Return the field id whose name best matches one of ``hints``.

    Prefers the most specific hint (earliest in the list) that any field name
    contains, so "actual start" beats a bare "start" when both exist.
    """
    lowered = [(f.field_id, (f.name or "").lower()) for f in fields]
    for hint in hints:
        for fid, name in lowered:
            if hint in name:
                return fid
    return None


def _current_values(client: JiraClient, issue_key: str, field_ids: list[str]) -> dict:
    if not field_ids:
        return {}
    data = client.get(
        f"/rest/api/3/issue/{issue_key}", params={"fields": ",".join(field_ids)}
    )
    return (data.get("fields") if isinstance(data, dict) else None) or {}


def apply_actual_dates(
    client: JiraClient,
    issue_key: str,
    *,
    started_at: datetime,
    ended_at: datetime | None,
) -> dict[str, str]:
    """Best-effort set actual start/end on ``issue_key``. Returns fields written.

    Never raises. ``started_at``/``ended_at`` are the session's UTC datetimes;
    the editmeta field type decides date-vs-datetime formatting (handled by
    update_issue_fields).
    """
    try:
        date_fields = get_editable_date_fields(client, issue_key)
    except JiraError as exc:
        logger.info("auto-dates: editmeta unavailable for %s: %s", issue_key, exc)
        return {}
    if not date_fields:
        return {}

    start_id = _match(date_fields, _START_HINTS)
    end_id = _match(date_fields, _END_HINTS)
    # Do not let the same field satisfy both roles.
    if end_id and end_id == start_id:
        end_id = None

    values: dict[str, str] = {}

    # Only set actual-start if empty, so we keep the first session's start.
    if start_id:
        try:
            current = _current_values(client, issue_key, [start_id])
        except JiraError:
            current = {}
        if not current.get(start_id):
            values[start_id] = started_at.isoformat()

    if end_id and ended_at is not None:
        values[end_id] = ended_at.isoformat()

    if not values:
        return {}

    try:
        update_issue_fields(client, issue_key, values, editable=date_fields)
        logger.info("auto-dates: set %s on %s", list(values.keys()), issue_key)
        return values
    except JiraError as exc:
        logger.info("auto-dates: write failed for %s: %s", issue_key, exc)
        return {}
