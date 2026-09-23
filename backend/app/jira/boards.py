"""Board operations via the Jira Agile API (section 5.2).

A board is backed by a saved filter and can span multiple projects, so board
operations use ``/rest/agile/1.0/board`` rather than the project REST API.
"""

from __future__ import annotations

from app.jira.client import JiraClient

_BOARD_PATH = "/rest/agile/1.0/board"


def list_boards(client: JiraClient, *, page_size: int = 50) -> list[dict]:
    """Fetch all boards, following the Agile API's startAt/isLast pagination."""
    boards: list[dict] = []
    start_at = 0
    while True:
        page = client.get(
            _BOARD_PATH, params={"startAt": start_at, "maxResults": page_size}
        )
        values = page.get("values", [])
        boards.extend(values)
        if page.get("isLast") or not values:
            break
        start_at += len(values)
    return boards


def get_board_configuration(client: JiraClient, board_id: int) -> dict:
    """Board configuration, which exposes the backing filter and location."""
    return client.get(f"{_BOARD_PATH}/{board_id}/configuration")


def normalize_board(raw: dict) -> dict:
    """Map a raw Agile board object to our ``boards`` columns.

    ``location`` carries the board's project (for project-scoped boards); a
    filter board spanning projects may have no single project, in which case
    project_key/project_id come back None and the app asks the user later.
    """
    location = raw.get("location") or {}
    project_key = None
    project_id = None
    if location.get("projectKey"):
        project_key = location.get("projectKey")
        project_id = str(location.get("projectId")) if location.get("projectId") else None
    elif location.get("type") == "project":
        project_key = location.get("key")
        project_id = str(location.get("id")) if location.get("id") is not None else None

    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "type": raw.get("type"),
        "project_key": project_key,
        "project_id": project_id,
    }


def resolve_project_from_configuration(config: dict) -> dict:
    """Pull the primary project key/id out of a board configuration payload."""
    location = config.get("location") or {}
    return {
        "project_key": location.get("projectKeyOrId") or location.get("key"),
        "project_id": str(location.get("id")) if location.get("id") is not None else None,
    }
