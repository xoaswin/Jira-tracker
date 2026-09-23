"""Manage-screen tests: editmeta date handling, auto-walk transitions, and the
subtask-block rule. The client is a lightweight fake (no network); the exact
Jira request/response shapes are asserted at the API layer in test_api_manage.py.
"""

import pytest

from app.jira.editmeta import EditableField, _format_value
from app.jira import transitions as tr


# --- editmeta value formatting ---

def test_format_date_field_trims_to_yyyy_mm_dd():
    f = EditableField(field_id="duedate", name="Due date", schema_type="date")
    assert _format_value(f, "2026-09-20") == "2026-09-20"
    assert _format_value(f, "2026-09-20T13:00:00.000+0000") == "2026-09-20"


def test_format_empty_clears_field():
    f = EditableField(field_id="duedate", name="Due date", schema_type="date")
    assert _format_value(f, "") is None
    assert _format_value(f, None) is None


def test_format_datetime_field_uses_offset_format():
    f = EditableField(field_id="customfield_1", name="Actual start", schema_type="datetime")
    out = _format_value(f, "2026-09-16T09:30:00+00:00")
    # Jira offset style: milliseconds + colon-free offset.
    assert out is not None and "." in out
    assert out.endswith("+0000")
    assert ":" not in out.split("T")[1][8:]  # no colon in the offset part


# --- auto-walk transitions ---

class FakeClient:
    """Simulates a Jira issue whose status advances as transitions are applied.

    ``flow`` maps a status name -> list of available transitions, each
    {id, name, to:{name, statusCategory:{key}}}. Applying a transition sets the
    current status to its ``to.name``.
    """

    def __init__(self, flow, start):
        self.flow = flow
        self.status = start
        self.applied = []

    def get(self, path, *, params=None):
        if path.endswith("/transitions"):
            return {"transitions": self.flow.get(self.status, [])}
        # issue fetch for status
        cat = _CATS[self.status]
        return {"fields": {"status": {"name": self.status, "statusCategory": {"key": cat}}}}

    def post(self, path, *, json_body=None, params=None):
        tid = json_body["transition"]["id"]
        for t in self.flow.get(self.status, []):
            if str(t["id"]) == str(tid):
                self.applied.append(t["name"])
                self.status = t["to"]["name"]
                return None
        raise AssertionError(f"transition {tid} not available from {self.status}")


_CATS = {"To Do": "new", "In Progress": "indeterminate", "Done": "done", "Draft": "new"}


def _t(id, name, to):
    return {"id": id, "name": name, "to": {"name": to, "statusCategory": {"key": _CATS[to]}}}


def test_walk_todo_to_done_applies_both_steps():
    flow = {
        "To Do": [_t(11, "Start", "In Progress")],
        "In Progress": [_t(21, "Finish", "Done")],
        "Done": [],
    }
    c = FakeClient(flow, "To Do")
    applied = tr.walk_to_status(c, "PPVM-1", "Done")
    assert applied == ["Start", "Finish"]
    assert c.status == "Done"


def test_walk_draft_to_done_three_steps():
    flow = {
        "Draft": [_t(1, "Submit", "To Do")],
        "To Do": [_t(11, "Start", "In Progress")],
        "In Progress": [_t(21, "Finish", "Done")],
        "Done": [],
    }
    c = FakeClient(flow, "Draft")
    applied = tr.walk_to_status(c, "PPVM-1", "Done")
    assert applied == ["Submit", "Start", "Finish"]
    assert c.status == "Done"


def test_walk_direct_transition_taken_immediately():
    flow = {"To Do": [_t(31, "Resolve", "Done")], "Done": []}
    c = FakeClient(flow, "To Do")
    applied = tr.walk_to_status(c, "PPVM-1", "Done")
    assert applied == ["Resolve"]


def test_walk_already_at_target_does_nothing():
    flow = {"Done": []}
    c = FakeClient(flow, "Done")
    applied = tr.walk_to_status(c, "PPVM-1", "Done")
    assert applied == []


def test_walk_does_not_overshoot_when_target_is_in_progress():
    # Target "In Progress" must stop there even if a Done transition exists.
    flow = {
        "To Do": [_t(11, "Start", "In Progress")],
        "In Progress": [_t(21, "Finish", "Done")],
    }
    c = FakeClient(flow, "To Do")
    applied = tr.walk_to_status(c, "PPVM-1", "In Progress")
    assert applied == ["Start"]
    assert c.status == "In Progress"
