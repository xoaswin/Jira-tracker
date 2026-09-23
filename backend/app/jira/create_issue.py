"""Issue creation (section 5.5).

    POST /rest/api/3/issue

``description`` is ADF (section 5.3). A subtask additionally needs
``fields.parent = {"key": "PAY-431"}`` and the parent must be in the same
project (section 5.5). Extra required custom fields collected from the user are
merged in verbatim.
"""

from __future__ import annotations

from app.jira.adf import rich_text_to_adf
from app.jira.client import JiraClient


def build_create_payload(
    *,
    project_key: str,
    issue_type_name: str,
    summary: str,
    description: str,
    parent_key: str | None = None,
    extra_fields: dict | None = None,
) -> dict:
    """Assemble the create-issue request body."""
    fields: dict = {
        "project": {"key": project_key},
        "issuetype": {"name": issue_type_name},
        "summary": summary,
        # Rich conversion so headings and the acceptance-criteria checklist
        # render as real Jira elements, not literal "h3."/"* [ ]" text.
        "description": rich_text_to_adf(description),
    }
    if parent_key:
        fields["parent"] = {"key": parent_key}
    if extra_fields:
        # User-supplied required custom fields (section 5.5). Merged verbatim so
        # the caller controls the exact shape Jira expects (option vs. array).
        fields.update(extra_fields)
    return {"fields": fields}


def create_issue(
    client: JiraClient,
    *,
    project_key: str,
    issue_type_name: str,
    summary: str,
    description: str,
    parent_key: str | None = None,
    extra_fields: dict | None = None,
) -> dict:
    """POST a new issue and return Jira's response (has ``id`` and ``key``)."""
    payload = build_create_payload(
        project_key=project_key,
        issue_type_name=issue_type_name,
        summary=summary,
        description=description,
        parent_key=parent_key,
        extra_fields=extra_fields,
    )
    return client.post("/rest/api/3/issue", json_body=payload)


def fetch_issue(client: JiraClient, issue_key: str, *, fields: list[str] | None = None) -> dict:
    """GET a single issue, used to cache a freshly created issue locally."""
    from app.jira.issues import DEFAULT_FIELDS

    field_param = ",".join(fields or DEFAULT_FIELDS)
    return client.get(f"/rest/api/3/issue/{issue_key}", params={"fields": field_param})
