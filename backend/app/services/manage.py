"""Ticket management service (Manage screen).

Assembles everything the Manage screen needs for one ticket, and drives the
edits, all via Jira (this is deliberate management of live tickets, distinct
from local work tracking):

* current status + available transitions,
* editable date/datetime fields (auto-discovered via editmeta),
* subtasks with their statuses (for the block-until-done cycle).

And the mutations:
* edit date fields,
* transition a subtask,
* mark the parent done, auto-walking the workflow, but only when every subtask
  is Done (the user's chosen rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.jira.adf import flatten_adf
from app.jira.client import JiraClient
from app.jira.datetime_fmt import parse_jira_datetime
from app.jira.editmeta import EditableField, get_editable_date_fields, update_issue_fields
from app.jira.transitions import get_transitions, walk_to_status
from app.jira.worklogs import add_worklog, get_worklogs, normalize_time_spent
from app.sync.idempotency import find_recent_duplicate_worklog

# Fields we fetch to render a manageable ticket.
_MANAGE_FIELDS = "summary,status,issuetype,duedate,subtasks,parent,assignee,priority"


@dataclass
class SubtaskView:
    issue_key: str
    summary: str
    status: str | None
    status_category: str | None
    is_done: bool


@dataclass
class ManageView:
    issue_key: str
    summary: str
    issue_type: str | None
    status: str | None
    status_category: str | None
    assignee_account_id: str | None = None
    assignee_name: str | None = None
    priority_id: str | None = None
    priority_name: str | None = None
    available_transitions: list[dict] = field(default_factory=list)
    date_fields: list[dict] = field(default_factory=list)
    subtasks: list[SubtaskView] = field(default_factory=list)


def _date_field_view(f: EditableField, current: dict) -> dict:
    return {
        "field_id": f.field_id,
        "name": f.name,
        "schema_type": f.schema_type,
        "value": current.get(f.field_id),
    }


def get_manage_view(client: JiraClient, issue_key: str) -> ManageView:
    """Fetch the full manageable view for a ticket."""
    # Include the editable date field ids so we can show their current values.
    date_fields = get_editable_date_fields(client, issue_key)
    date_ids = [f.field_id for f in date_fields]
    field_param = _MANAGE_FIELDS + ("," + ",".join(date_ids) if date_ids else "")

    data = client.get(f"/rest/api/3/issue/{issue_key}", params={"fields": field_param})
    fields = data.get("fields") or {}

    status = fields.get("status") or {}
    status_cat = (status.get("statusCategory") or {}).get("name")
    assignee = fields.get("assignee") or {}
    priority = fields.get("priority") or {}

    subtasks: list[SubtaskView] = []
    for st in fields.get("subtasks") or []:
        sf = st.get("fields") or {}
        st_status = sf.get("status") or {}
        cat = (st_status.get("statusCategory") or {}).get("key")
        subtasks.append(
            SubtaskView(
                issue_key=st.get("key"),
                summary=sf.get("summary") or "",
                status=st_status.get("name"),
                status_category=(st_status.get("statusCategory") or {}).get("name"),
                is_done=(cat or "").lower() == "done",
            )
        )

    transitions = [
        {"id": str(t.get("id")), "name": t.get("name"),
         "to": (t.get("to") or {}).get("name")}
        for t in get_transitions(client, issue_key)
    ]

    return ManageView(
        issue_key=issue_key,
        summary=fields.get("summary") or "",
        issue_type=(fields.get("issuetype") or {}).get("name"),
        status=status.get("name"),
        status_category=status_cat,
        assignee_account_id=assignee.get("accountId"),
        assignee_name=assignee.get("displayName"),
        priority_id=str(priority["id"]) if priority.get("id") is not None else None,
        priority_name=priority.get("name"),
        available_transitions=transitions,
        date_fields=[_date_field_view(f, fields) for f in date_fields],
        subtasks=subtasks,
    )


def edit_dates(client: JiraClient, issue_key: str, values: dict[str, str | None]) -> None:
    """Update editable date fields on the ticket."""
    update_issue_fields(client, issue_key, values)


def all_subtasks_done(client: JiraClient, issue_key: str) -> tuple[bool, list[SubtaskView]]:
    """Return (all_done, subtasks). all_done is True if there are no subtasks or
    every subtask is in the Done category."""
    view = get_manage_view(client, issue_key)
    if not view.subtasks:
        return True, []
    return all(st.is_done for st in view.subtasks), view.subtasks


class SubtasksIncompleteError(Exception):
    """Raised when marking a parent Done is blocked by unfinished subtasks."""

    def __init__(self, pending: list[str]):
        self.pending = pending
        super().__init__(f"{len(pending)} subtask(s) not Done: {', '.join(pending)}")


def mark_done(client: JiraClient, issue_key: str, target_name: str = "Done") -> list[str]:
    """Auto-walk the ticket to Done, but only if all subtasks are Done first.

    Raises SubtasksIncompleteError if any subtask is unfinished (the block rule).
    Returns the list of transition names applied.
    """
    done, subtasks = all_subtasks_done(client, issue_key)
    if not done:
        pending = [st.issue_key for st in subtasks if not st.is_done]
        raise SubtasksIncompleteError(pending)
    return walk_to_status(client, issue_key, target_name)


def transition_subtask(client: JiraClient, subtask_key: str, target_name: str) -> list[str]:
    """Walk a subtask to a target status (used to mark a subtask Done)."""
    return walk_to_status(client, subtask_key, target_name)


class SubtaskCreateError(Exception):
    """Raised when a subtask cannot be created (no sub-task type in project)."""


def create_subtask(db, client: JiraClient, parent_key: str, summary: str) -> str:
    """Create a Sub-task under ``parent_key`` and return the new key.

    Resolves the parent's project and board, and the project's actual sub-task
    issue-type name (which varies: "Sub-task", "Subtask", "Sub Task"). Caches the
    new issue locally like the main creation flow.
    """
    if not (summary or "").strip():
        raise SubtaskCreateError("A subtask needs a summary.")

    # Learn the parent's project + board so the new subtask is cached correctly.
    from app.jira.createmeta import get_issue_types
    from app.models import Issue
    from app.services.issue_create import create_and_cache

    parent = client.get(
        f"/rest/api/3/issue/{parent_key}", params={"fields": "project"}
    )
    project_key = ((parent.get("fields") or {}).get("project") or {}).get("key")
    if not project_key and "-" in parent_key:
        project_key = parent_key.rsplit("-", 1)[0]
    if not project_key:
        raise SubtaskCreateError(f"Could not resolve the project for {parent_key}.")

    # The board id from our local cache of the parent (best-effort; None is fine).
    from sqlalchemy import select

    board_id = db.execute(
        select(Issue.board_id).where(Issue.issue_key == parent_key)
    ).scalar_one_or_none()

    # Find the project's sub-task issue type by its ``subtask`` flag, not a
    # hard-coded name (instances differ).
    subtask_type = next(
        (t for t in get_issue_types(client, project_key) if t.subtask), None
    )
    if subtask_type is None:
        raise SubtaskCreateError(
            f"Project {project_key} has no sub-task issue type enabled."
        )

    issue = create_and_cache(
        db,
        client,
        board_id=board_id,
        project_key=project_key,
        issue_type_name=subtask_type.name,
        summary=summary.strip(),
        description="",
        parent_key=parent_key,
    )
    return issue.issue_key


class NoTimeError(Exception):
    """Raised when a worklog is submitted with zero total time."""


def log_work(
    client: JiraClient,
    issue_key: str,
    *,
    hours: int,
    minutes: int,
    started: str | None,
    comment: str | None,
    account_id: str | None = None,
) -> tuple[dict, bool]:
    """Post a worklog to a ticket. Returns (created_worklog, rounded_up).

    Total time is hours*3600 + minutes*60. ``started`` is an ISO string from the
    UI (assumed local/naive -> UTC) or None for now. Raises NoTimeError if the
    total is zero, so the UI can show a clear message instead of a Jira 400.

    Idempotency: Jira worklog creation has no idempotency key, and this path
    posts directly (not via the outbox). A double-submit (rapid clicks, a stale
    duplicate-mounted component, a client retry) would otherwise create multiple
    identical worklogs and silently inflate logged hours. So before posting we
    check for a matching worklog created in the last couple of minutes and, if
    found, return it instead of posting again.
    """
    total_seconds = max(0, int(hours)) * 3600 + max(0, int(minutes)) * 60
    if total_seconds <= 0:
        raise NoTimeError("Enter a duration greater than zero.")

    when = parse_jira_datetime(started) if started else datetime.now(timezone.utc)
    send_seconds, rounded_up = normalize_time_spent(total_seconds)

    existing_id = find_recent_duplicate_worklog(
        client,
        issue_key,
        account_id,
        when,
        send_seconds,
        comment,
    )
    if existing_id is not None:
        return {"id": existing_id, "timeSpentSeconds": send_seconds,
                "started": None, "comment": comment, "author": None}, rounded_up

    worklog = add_worklog(
        client, issue_key, when, total_seconds, comment_text=comment or None
    )
    return worklog, rounded_up


def _worklog_view(raw: dict) -> dict:
    """Shape a raw Jira worklog into what the UI shows."""
    return {
        "id": str(raw.get("id")),
        "time_spent_seconds": int(raw.get("timeSpentSeconds") or 0),
        "started": raw.get("started"),
        "comment": flatten_adf(raw.get("comment")) or None,
        "author": (raw.get("author") or {}).get("displayName"),
    }


def list_worklogs(client: JiraClient, issue_key: str) -> list[dict]:
    """Recent worklogs on an issue, newest first (for the Manage panel)."""
    raws = get_worklogs(client, issue_key)
    views = [_worklog_view(r) for r in raws]
    views.sort(key=lambda w: w.get("started") or "", reverse=True)
    return views
