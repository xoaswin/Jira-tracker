"""Issue fetching and normalisation.

Two read paths:

* :func:`fetch_board_issues` uses the Agile board issue endpoint
  (``/rest/agile/1.0/board/{id}/issue``), which is offset-paginated
  (startAt/maxResults) and is the right tool for "my open issues on this board".
* :func:`enhanced_search` uses the newer cursor-paginated JQL search endpoint
  (``/rest/api/3/search/jql`` with ``nextPageToken``), used later for the
  project-wide duplicate guard (section 7).

Search responses only return the fields you ask for (section 5.1), so we always
pass an explicit field list.
"""

from __future__ import annotations

from app.jira.adf import flatten_adf
from app.jira.client import JiraClient
from app.jira.datetime_fmt import parse_jira_datetime

# The fields we need for matching and display (section 5.2).
DEFAULT_FIELDS = [
    "summary",
    "description",
    "issuetype",
    "status",
    "parent",
    "assignee",
    "updated",
    "sprint",
    "project",
]

# The JQL used to select which issues on a board get cached and made matchable.
#
# Default: all open (not-Done) issues on the board, any assignee. This lets you
# log against a colleague's in-progress ticket, not just your own. The original
# spec scoped this to "assignee = currentUser()"; that narrower query is kept
# below and can be selected via the ``issue_scope`` setting.
OPEN_ON_BOARD_JQL = "statusCategory != Done ORDER BY updated DESC"

# "Issues assigned to me on this board" (section 5.2). The narrower alternative.
ASSIGNED_TO_ME_JQL = (
    "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
)

# Named scopes selectable in settings. Maps a short key to its JQL.
ISSUE_SCOPE_JQL = {
    "open_on_board": OPEN_ON_BOARD_JQL,
    "assigned_to_me": ASSIGNED_TO_ME_JQL,
    "mine_all_status": "assignee = currentUser() ORDER BY updated DESC",
    "all_on_board": "ORDER BY updated DESC",
}
DEFAULT_ISSUE_SCOPE = "open_on_board"


def fetch_board_issues(
    client: JiraClient,
    board_id: int,
    *,
    jql: str = OPEN_ON_BOARD_JQL,
    fields: list[str] | None = None,
    page_size: int = 50,
) -> list[dict]:
    """Fetch raw issues on a board via the offset-paginated Agile endpoint."""
    fields = fields or DEFAULT_FIELDS
    field_param = ",".join(fields)
    path = f"/rest/agile/1.0/board/{board_id}/issue"
    issues: list[dict] = []
    start_at = 0
    while True:
        page = client.get(
            path,
            params={
                "jql": jql,
                "fields": field_param,
                "startAt": start_at,
                "maxResults": page_size,
            },
        )
        batch = page.get("issues", [])
        issues.extend(batch)
        total = page.get("total")
        start_at += len(batch)
        if not batch:
            break
        if total is not None and start_at >= total:
            break
        if len(batch) < page_size:
            break
    return issues


def enhanced_search(
    client: JiraClient,
    jql: str,
    *,
    fields: list[str] | None = None,
    page_size: int = 50,
    max_results: int | None = None,
) -> list[dict]:
    """Cursor-paginated JQL search (``/rest/api/3/search/jql``).

    Loops on ``nextPageToken`` rather than incrementing startAt (section 5.1).
    """
    fields = fields or DEFAULT_FIELDS
    issues: list[dict] = []
    next_token: str | None = None
    while True:
        params: dict = {
            "jql": jql,
            "fields": ",".join(fields),
            "maxResults": page_size,
        }
        if next_token:
            params["nextPageToken"] = next_token
        page = client.get("/rest/api/3/search/jql", params=params)
        batch = page.get("issues", [])
        issues.extend(batch)
        if max_results is not None and len(issues) >= max_results:
            return issues[:max_results]
        next_token = page.get("nextPageToken")
        if page.get("isLast") or not next_token or not batch:
            break
    return issues


def normalize_issue(raw: dict, board_id: int | None = None) -> dict:
    """Map a raw Jira issue to our ``issues`` columns.

    Robust to description arriving as None, a plain string, or an ADF dict
    (section 5.3), and to the ``sprint`` field being a dict, a list, or absent.
    """
    fields = raw.get("fields", {}) or {}

    issue_type = (fields.get("issuetype") or {}).get("name")
    status_obj = fields.get("status") or {}
    status = status_obj.get("name")
    status_category = (status_obj.get("statusCategory") or {}).get("name")
    parent_key = (fields.get("parent") or {}).get("key")
    assignee = fields.get("assignee") or {}
    assignee_account_id = assignee.get("accountId")
    assignee_name = assignee.get("displayName")

    project_key = (fields.get("project") or {}).get("key")
    issue_key = raw.get("key")
    if not project_key and issue_key and "-" in issue_key:
        project_key = issue_key.rsplit("-", 1)[0]

    updated_raw = fields.get("updated")
    updated_at = parse_jira_datetime(updated_raw) if updated_raw else None

    return {
        "jira_id": str(raw.get("id")),
        "issue_key": issue_key,
        "board_id": board_id,
        "project_key": project_key,
        "issue_type": issue_type,
        "parent_key": parent_key,
        "summary": fields.get("summary") or "",
        "description_text": flatten_adf(fields.get("description")),
        "status": status,
        "status_category": status_category,
        "assignee_account_id": assignee_account_id,
        "assignee_name": assignee_name,
        "sprint_name": _extract_sprint_name(fields.get("sprint")),
        "updated_at": updated_at,
    }


def _extract_sprint_name(sprint) -> str | None:
    """Sprint can be a dict, a list of sprints, or absent."""
    if not sprint:
        return None
    if isinstance(sprint, dict):
        return sprint.get("name")
    if isinstance(sprint, list) and sprint:
        last = sprint[-1]
        if isinstance(last, dict):
            return last.get("name")
    return None
