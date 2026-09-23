"""Assignee and priority helpers for the Manage screen.

Reassigning and reprioritising are two of the most common ticket edits, so the
Manage screen exposes them directly. Jira specifics handled here:

* Assignee is set via ``PUT /issue/{key}/assignee`` with ``{"accountId": ...}``
  (Cloud). ``accountId: null`` unassigns.
* Assignable users come from ``/user/assignable/search?issueKey=`` (scoped to who
  can actually be assigned this issue), with a query for type-ahead.
* Priorities are a global list from ``/priority``; the value is set through the
  normal field update (``PUT /issue/{key}`` with ``{"fields": {"priority": ...}}``).
"""

from __future__ import annotations

from app.jira.client import JiraClient

# Cap the assignable-user list so a huge org does not flood the picker.
_MAX_ASSIGNABLE = 50


def search_assignable_users(
    client: JiraClient, issue_key: str, query: str = ""
) -> list[dict]:
    """Users who can be assigned ``issue_key``, optionally filtered by ``query``.

    Returns [{account_id, display_name, email}]. ``query`` matches display name
    or email (Jira's type-ahead). Empty query returns the first page.
    """
    params = {"issueKey": issue_key, "maxResults": _MAX_ASSIGNABLE}
    # Jira Cloud uses ``query`` for assignable search; omit when blank so we get
    # the default first page rather than an empty match.
    if query.strip():
        params["query"] = query.strip()
    result = client.get("/rest/api/3/user/assignable/search", params=params)
    users = result if isinstance(result, list) else []
    return [
        {
            "account_id": u.get("accountId"),
            "display_name": u.get("displayName"),
            "email": u.get("emailAddress"),
        }
        for u in users
    ]


def set_assignee(client: JiraClient, issue_key: str, account_id: str | None) -> None:
    """Assign ``issue_key`` to ``account_id`` (None unassigns)."""
    client.request(
        "PUT",
        f"/rest/api/3/issue/{issue_key}/assignee",
        json_body={"accountId": account_id},
    )


def list_priorities(client: JiraClient) -> list[dict]:
    """All priorities configured on the instance: [{id, name}]."""
    result = client.get("/rest/api/3/priority")
    items = result if isinstance(result, list) else []
    return [{"id": str(p.get("id")), "name": p.get("name")} for p in items]


def set_priority(client: JiraClient, issue_key: str, priority_id: str) -> None:
    """Set the priority field on ``issue_key`` by priority id."""
    client.request(
        "PUT",
        f"/rest/api/3/issue/{issue_key}",
        json_body={"fields": {"priority": {"id": str(priority_id)}}},
    )
