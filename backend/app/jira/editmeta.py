"""Editable-field discovery and issue field updates (Manage screen).

We cannot know a Jira instance's custom field IDs in advance ("start date",
"actual start/end" are almost always custom fields with instance-specific ids),
so we ask Jira per issue:

    GET /rest/api/3/issue/{key}/editmeta  -> the fields editable on THIS issue,
                                             each with a schema (type/format).

From that we surface the editable date and datetime fields (plus the standard
``duedate``) for the UI, and write them back with:

    PUT /rest/api/3/issue/{key}         { "fields": { ... } }

Jira date fields take ``yyyy-MM-dd``; datetime fields take the full offset
format (reuse jira_datetime). We never guess a field id; if a field is not in
editmeta it is not editable and we do not show it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.jira.client import JiraClient
from app.jira.datetime_fmt import jira_datetime


@dataclass
class EditableField:
    field_id: str
    name: str
    schema_type: str  # "date" | "datetime" | "string" | ...
    schema_format: str | None = None  # e.g. "date" | "date-time"


# Jira schema types/formats that represent dates we let the user edit here.
_DATE_TYPES = {"date"}
_DATETIME_TYPES = {"datetime"}


def get_editmeta_fields(client: JiraClient, issue_key: str) -> list[EditableField]:
    """Return the fields editable on this issue (from editmeta)."""
    result = client.get(f"/rest/api/3/issue/{issue_key}/editmeta")
    raw = (result.get("fields") if isinstance(result, dict) else None) or {}
    out: list[EditableField] = []
    for field_id, meta in raw.items():
        schema = meta.get("schema") or {}
        out.append(
            EditableField(
                field_id=field_id,
                name=meta.get("name") or field_id,
                schema_type=schema.get("type") or "string",
                schema_format=schema.get("format"),
            )
        )
    return out


def get_editable_date_fields(client: JiraClient, issue_key: str) -> list[EditableField]:
    """Just the editable date / datetime fields on this issue (for the UI)."""
    return [
        f
        for f in get_editmeta_fields(client, issue_key)
        if f.schema_type in _DATE_TYPES or f.schema_type in _DATETIME_TYPES
    ]


def _format_value(field: EditableField, value: str | None) -> str | None:
    """Coerce a UI value to the shape Jira expects for this field's type.

    * date      -> "yyyy-MM-dd" (pass through; the UI sends that from <input date>)
    * datetime  -> full offset format via jira_datetime
    * empty/None-> None, which clears the field.
    """
    if value is None or value == "":
        return None
    if field.schema_type in _DATETIME_TYPES:
        # Accept an ISO string from the UI and reformat to Jira's offset style.
        try:
            from app.jira.datetime_fmt import parse_jira_datetime

            return jira_datetime(parse_jira_datetime(value))
        except (ValueError, OverflowError):
            return value
    # date type: Jira wants yyyy-MM-dd. Trim a datetime if one slipped in.
    return value[:10]


def update_issue_fields(
    client: JiraClient,
    issue_key: str,
    values: dict[str, str | None],
    editable: list[EditableField] | None = None,
) -> None:
    """PUT field updates for an issue.

    ``values`` maps field_id -> raw UI value. Only fields present in the issue's
    editmeta are sent (so we never attempt to write a non-editable field). A
    None/empty value clears that field.
    """
    editable = editable if editable is not None else get_editmeta_fields(client, issue_key)
    by_id = {f.field_id: f for f in editable}

    fields: dict = {}
    for field_id, raw in values.items():
        f = by_id.get(field_id)
        if f is None:
            continue  # not editable on this issue; skip rather than 400
        fields[field_id] = _format_value(f, raw)

    if not fields:
        return
    client.request("PUT", f"/rest/api/3/issue/{issue_key}", json_body={"fields": fields})
