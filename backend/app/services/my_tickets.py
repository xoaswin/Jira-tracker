"""My Tickets: everything assigned to the connected user, with due-date urgency.

Distinct from the board issue cache (which is scoped per board and may include
other people's tickets). This asks Jira directly for *my* work across all
projects and flags what needs attention:

    overdue    due date is in the past and the ticket is not Done
    due_today  due date is today
    due_soon   due date within the next ``SOON_DAYS`` days
    scheduled  has a due date further out
    no_due     no due date set

Sorted so the most urgent surface first. Read-only and live; never cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.jira.client import JiraClient
from app.jira.datetime_fmt import parse_jira_datetime

# "Due within this many days" counts as due_soon (not counting today).
SOON_DAYS = 3

# We want the open work first, but also show recently-updated done items? No:
# keep it to open work — that is what "needs my attention" means. Done items
# are excluded so the list stays actionable.
MY_TICKETS_JQL = (
    "assignee = currentUser() AND statusCategory != Done ORDER BY duedate ASC, updated DESC"
)

_FIELDS = ["summary", "status", "issuetype", "duedate", "priority", "project"]

# Urgency ranking for sorting (lower = more urgent).
_URGENCY_RANK = {
    "overdue": 0,
    "due_today": 1,
    "due_soon": 2,
    "scheduled": 3,
    "no_due": 4,
}


@dataclass
class MyTicket:
    issue_key: str
    summary: str
    issue_type: str | None
    status: str | None
    status_category: str | None
    priority: str | None
    project_key: str | None
    due_date: str | None  # "yyyy-MM-dd" or None
    urgency: str
    days_until_due: int | None  # negative if overdue, 0 today, positive if future


def _classify(due: date | None, today: date, is_done: bool) -> tuple[str, int | None]:
    """Return (urgency, days_until_due) for a due date relative to today."""
    if due is None:
        return "no_due", None
    delta = (due - today).days
    if is_done:
        # A done ticket is never "overdue" for attention purposes.
        return ("scheduled" if delta > 0 else "no_due"), delta
    if delta < 0:
        return "overdue", delta
    if delta == 0:
        return "due_today", 0
    if delta <= SOON_DAYS:
        return "due_soon", delta
    return "scheduled", delta


def _to_ticket(raw: dict, today: date) -> MyTicket:
    fields = raw.get("fields") or {}
    status_obj = fields.get("status") or {}
    status_cat = (status_obj.get("statusCategory") or {}).get("name")
    is_done = ((status_obj.get("statusCategory") or {}).get("key") or "").lower() == "done"

    due_raw = fields.get("duedate")
    due: date | None = None
    if due_raw:
        try:
            due = parse_jira_datetime(due_raw).date()
        except (ValueError, OverflowError):
            due = None

    urgency, days = _classify(due, today, is_done)
    project = fields.get("project") or {}
    return MyTicket(
        issue_key=raw.get("key"),
        summary=fields.get("summary") or "",
        issue_type=(fields.get("issuetype") or {}).get("name"),
        status=status_obj.get("name"),
        status_category=status_cat,
        priority=(fields.get("priority") or {}).get("name"),
        project_key=project.get("key"),
        due_date=due.isoformat() if due else None,
        urgency=urgency,
        days_until_due=days,
    )


def get_my_tickets(client: JiraClient, *, now: datetime | None = None) -> list[MyTicket]:
    """Fetch all open tickets assigned to the connected user, urgency-ranked."""
    today = (now or datetime.now()).date()
    raws = enhanced_search_my_issues(client)
    tickets = [_to_ticket(r, today) for r in raws]
    # Stable sort: urgency bucket first, then soonest due date within a bucket.
    tickets.sort(
        key=lambda t: (
            _URGENCY_RANK.get(t.urgency, 99),
            t.days_until_due if t.days_until_due is not None else 10_000,
        )
    )
    return tickets


def enhanced_search_my_issues(client: JiraClient) -> list[dict]:
    """The raw JQL search for my open issues (split out for testability)."""
    from app.jira.issues import enhanced_search

    return enhanced_search(client, MY_TICKETS_JQL, fields=_FIELDS, max_results=200)
