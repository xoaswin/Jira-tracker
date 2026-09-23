"""Create an issue in Jira and cache it locally (Phase 4, section 5.5).

This is the single confirmed write to Jira in the creation flow (section 15
rule 1). The route only calls this after the user has confirmed the drafted
issue. On success the new issue is fetched and cached in the local ``issues``
table so it appears in matching immediately, with its embedding computed
best-effort.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jira.client import JiraClient
from app.jira.create_issue import create_issue, fetch_issue
from app.jira.issues import normalize_issue
from app.models import Board, Issue, utcnow
from app.services.matching import ensure_embeddings

logger = logging.getLogger("jira_tracker.issue_create")


def create_and_cache(
    db: Session,
    client: JiraClient,
    *,
    board_id: int,
    project_key: str,
    issue_type_name: str,
    summary: str,
    description: str,
    parent_key: str | None = None,
    extra_fields: dict | None = None,
) -> Issue:
    """Create the issue in Jira, then fetch and cache it locally."""
    created = create_issue(
        client,
        project_key=project_key,
        issue_type_name=issue_type_name,
        summary=summary,
        description=description,
        parent_key=parent_key,
        extra_fields=extra_fields,
    )
    issue_key = created.get("key")
    logger.info("created issue %s in project %s", issue_key, project_key)

    # Drop the new issue into the board's active sprint so it lands on the
    # current board, not the backlog. Sub-tasks inherit their parent's sprint,
    # so we skip them. Best-effort: a kanban board (no sprints) or an API hiccup
    # must never undo a successful creation.
    is_subtask = issue_type_name.strip().lower() in {"sub-task", "subtask"}
    if not is_subtask and issue_key:
        try:
            from app.jira.sprints import add_issue_to_sprint, get_active_sprint_id

            sprint_id = get_active_sprint_id(client, board_id)
            if sprint_id is not None:
                add_issue_to_sprint(client, sprint_id, issue_key)
                logger.info("added %s to active sprint %s", issue_key, sprint_id)
        except Exception:  # noqa: BLE001 - creation already succeeded
            logger.warning("could not add %s to active sprint", issue_key, exc_info=True)

    # Fetch the full issue so the local cache has status, sprint, etc. If the
    # fetch fails we still return a minimal cached row from the create response.
    try:
        full = fetch_issue(client, issue_key)
        data = normalize_issue(full, board_id=board_id)
    except Exception:  # noqa: BLE001 - cache best-effort, creation already done
        logger.warning("could not fetch created issue %s; caching minimal row", issue_key)
        data = {
            "jira_id": str(created.get("id")),
            "issue_key": issue_key,
            "board_id": board_id,
            "project_key": project_key,
            "issue_type": issue_type_name,
            "parent_key": parent_key,
            "summary": summary,
            "description_text": description,
            "status": None,
            "status_category": None,
            "assignee_account_id": None,
            "sprint_name": None,
            "updated_at": utcnow(),
        }

    issue = db.execute(
        select(Issue).where(Issue.jira_id == data["jira_id"])
    ).scalar_one_or_none()
    if issue is None:
        issue = Issue(jira_id=data["jira_id"])
        db.add(issue)
    for field_name, value in data.items():
        setattr(issue, field_name, value)
    issue.last_synced_at = utcnow()
    db.commit()
    db.refresh(issue)

    # Compute the embedding for the new issue best-effort (no-op if unavailable).
    from app.services.matching import _embedding_model_name

    ensure_embeddings(db, [issue], _embedding_model_name(db))
    return issue
