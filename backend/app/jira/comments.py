"""Comment creation and reading (section 5.3). The ``body`` field is ADF."""

from __future__ import annotations

from app.jira.adf import text_to_adf
from app.jira.client import JiraClient


def add_comment(client: JiraClient, issue_key: str, body_text: str) -> dict:
    """POST /rest/api/3/issue/{key}/comment -> the created comment (has ``id``)."""
    payload = {"body": text_to_adf(body_text)}
    return client.post(f"/rest/api/3/issue/{issue_key}/comment", json_body=payload)


def get_comments(client: JiraClient, issue_key: str) -> list[dict]:
    """GET all comments on an issue (used by the Phase 2 idempotency check)."""
    result = client.get(f"/rest/api/3/issue/{issue_key}/comment")
    return result.get("comments", []) if isinstance(result, dict) else []
