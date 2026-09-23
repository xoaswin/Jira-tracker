"""Create-metadata discovery for issue creation (section 5.5).

Before creating an issue we must discover which fields the target project and
issue type require, because admins add mandatory custom fields that otherwise
produce a cryptic 400. Atlassian split the old single ``createmeta`` endpoint
into two cursor-friendly endpoints on newer Jira Cloud:

    GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes
        -> the issue types available in the project
    GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes/{issueTypeId}
        -> the fields (with ``required`` flags) for one issue type

We use these two. Fields the app fills automatically (summary, description,
project, issuetype, parent) are never surfaced to the user; anything else that
is ``required`` is returned so the confirmation dialog can collect it (section
5.5: "render it in the confirmation dialog and let me fill it in").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.jira.client import JiraClient

# Fields the app supplies itself; never ask the user for these.
AUTO_FILLED_FIELDS = {"summary", "description", "project", "issuetype", "parent"}


@dataclass
class RequiredField:
    """A required field the app cannot fill automatically."""

    field_id: str
    name: str
    schema_type: str  # "string" | "option" | "array" | "number" | ...
    # For option/array-of-option fields, the allowed values, each {id, value/name}.
    allowed_values: list[dict] = field(default_factory=list)


@dataclass
class IssueTypeMeta:
    id: str
    name: str
    subtask: bool


def get_issue_types(client: JiraClient, project_key: str) -> list[IssueTypeMeta]:
    """List creatable issue types for a project."""
    path = f"/rest/api/3/issue/createmeta/{project_key}/issuetypes"
    result = client.get(path)
    raw_types = result.get("issueTypes", result.get("values", [])) if isinstance(result, dict) else []
    types: list[IssueTypeMeta] = []
    for t in raw_types:
        types.append(
            IssueTypeMeta(
                id=str(t.get("id")),
                name=t.get("name") or "",
                subtask=bool(t.get("subtask", False)),
            )
        )
    return types


def find_issue_type(
    client: JiraClient, project_key: str, type_name: str
) -> IssueTypeMeta | None:
    """Find an issue type by name (case-insensitive) within a project."""
    target = type_name.strip().lower()
    for t in get_issue_types(client, project_key):
        if t.name.lower() == target:
            return t
    return None


def get_required_fields(
    client: JiraClient, project_key: str, issue_type_id: str
) -> list[RequiredField]:
    """Return the required fields for a project + issue type minus auto-filled.

    Robust to the two response shapes: a ``fields`` list (newer) or a ``values``
    list. Each field carries ``required`` and a ``schema`` with a ``type``.
    """
    path = f"/rest/api/3/issue/createmeta/{project_key}/issuetypes/{issue_type_id}"
    result = client.get(path)
    raw_fields = []
    if isinstance(result, dict):
        raw_fields = result.get("fields") or result.get("values") or []

    required: list[RequiredField] = []
    for f in raw_fields:
        field_id = f.get("fieldId") or f.get("key") or f.get("id")
        if not field_id or field_id in AUTO_FILLED_FIELDS:
            continue
        if not f.get("required", False):
            continue
        schema = f.get("schema") or {}
        required.append(
            RequiredField(
                field_id=field_id,
                name=f.get("name") or field_id,
                schema_type=schema.get("type") or "string",
                allowed_values=f.get("allowedValues") or [],
            )
        )
    return required
