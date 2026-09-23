"""Sprint operations via the Jira Agile API.

Used to drop a newly created issue into the board's active sprint, so new work
lands on the current board instead of the backlog. Only scrum boards have
sprints; kanban boards return 400 here, which callers treat as "no sprint".
"""

from __future__ import annotations

import logging

from app.jira.client import JiraClient, JiraError

logger = logging.getLogger("jira_tracker.sprints")


def get_active_sprint_id(client: JiraClient, board_id: int) -> int | None:
    """Return the board's active sprint id, or None.

    Kanban boards (and boards with no sprint running) yield None rather than
    raising, so issue creation never breaks on a missing sprint.
    """
    try:
        data = client.get(
            f"/rest/agile/1.0/board/{board_id}/sprint",
            params={"state": "active", "maxResults": 1},
        )
    except JiraError as exc:
        # 400 = board doesn't support sprints (kanban); anything else we also
        # treat as "no sprint" so creation is never blocked.
        logger.info("no active sprint for board %s: %s", board_id, exc)
        return None
    values = data.get("values") if isinstance(data, dict) else None
    if not values:
        return None
    sprint_id = values[0].get("id")
    return int(sprint_id) if sprint_id is not None else None


def add_issue_to_sprint(client: JiraClient, sprint_id: int, issue_key: str) -> None:
    """Move an issue into a sprint. Raises JiraError on failure (caller guards)."""
    client.post(
        f"/rest/agile/1.0/sprint/{sprint_id}/issue",
        json_body={"issues": [issue_key]},
    )
