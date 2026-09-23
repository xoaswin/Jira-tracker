"""Issue caching: refresh a board's issues and read them back.

Which issues get cached is controlled by the ``issue_scope`` setting (default
"open_on_board" = all not-Done issues, any assignee), resolved to JQL here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jira.client import JiraClient
from app.jira.issues import (
    DEFAULT_ISSUE_SCOPE,
    ISSUE_SCOPE_JQL,
    fetch_board_issues,
    normalize_issue,
)
from app.models import AppSettings, Issue, utcnow


def _scope_jql(db: Session) -> str:
    """Resolve the configured issue scope to its JQL, falling back to default."""
    row = db.get(AppSettings, 1)
    scope = (row.issue_scope if row and row.issue_scope else DEFAULT_ISSUE_SCOPE)
    return ISSUE_SCOPE_JQL.get(scope, ISSUE_SCOPE_JQL[DEFAULT_ISSUE_SCOPE])


def refresh_board_issues(db: Session, client: JiraClient, board_id: int) -> list[Issue]:
    """Fetch the in-scope issues on a board and replace this board's cached set.

    Issues no longer returned by the scope query (closed, moved) are dropped for
    this board.
    """
    raw_issues = fetch_board_issues(client, board_id, jql=_scope_jql(db))
    now = utcnow()
    fresh_keys: set[str] = set()

    for raw in raw_issues:
        data = normalize_issue(raw, board_id=board_id)
        fresh_keys.add(data["issue_key"])
        issue = db.execute(
            select(Issue).where(Issue.jira_id == data["jira_id"])
        ).scalar_one_or_none()
        if issue is None:
            issue = Issue(jira_id=data["jira_id"])
            db.add(issue)
        for field, value in data.items():
            setattr(issue, field, value)
        issue.last_synced_at = now

    # Drop stale issues for this board that were not in the fresh set.
    existing = db.execute(select(Issue).where(Issue.board_id == board_id)).scalars().all()
    for issue in existing:
        if issue.issue_key not in fresh_keys:
            db.delete(issue)

    db.commit()
    return list_cached_issues(db, board_id)


def list_cached_issues(db: Session, board_id: int) -> list[Issue]:
    stmt = (
        select(Issue)
        .where(Issue.board_id == board_id)
        .order_by(Issue.updated_at.desc().nullslast())
    )
    return list(db.execute(stmt).scalars().all())
