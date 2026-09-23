"""Tests for auto-stamping actual start/end dates from a session."""

import json
from datetime import datetime, timezone

import httpx
import respx

from app.jira.client import JiraClient
from app.services.auto_dates import apply_actual_dates

BASE = "https://acme.atlassian.net"


def _client():
    return JiraClient(BASE, "me@acme.com", "tok", timeout=5.0)


def _editmeta(rmock, key, fields):
    rmock.get(f"{BASE}/rest/api/3/issue/{key}/editmeta").mock(
        return_value=httpx.Response(200, json={"fields": fields})
    )


START = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc)


@respx.mock
def test_sets_actual_start_when_empty_and_end():
    c = _client()
    _editmeta(
        rmock=respx,
        key="PAY-1",
        fields={
            "customfield_1": {"name": "Actual start", "schema": {"type": "date"}},
            "customfield_2": {"name": "Actual end", "schema": {"type": "date"}},
        },
    )
    # Current values: actual start empty.
    respx.get(f"{BASE}/rest/api/3/issue/PAY-1").mock(
        return_value=httpx.Response(200, json={"fields": {"customfield_1": None}})
    )
    put = respx.put(f"{BASE}/rest/api/3/issue/PAY-1").mock(return_value=httpx.Response(204))

    written = apply_actual_dates(c, "PAY-1", started_at=START, ended_at=END)
    assert "customfield_1" in written  # actual start
    assert "customfield_2" in written  # actual end
    sent = json.loads(put.calls.last.request.read().decode())["fields"]
    assert sent["customfield_1"] == "2026-09-18"  # date type -> yyyy-MM-dd
    assert sent["customfield_2"] == "2026-09-18"
    c.close()


@respx.mock
def test_does_not_overwrite_existing_actual_start():
    c = _client()
    _editmeta(
        rmock=respx,
        key="PAY-2",
        fields={
            "customfield_1": {"name": "Actual start", "schema": {"type": "date"}},
            "customfield_2": {"name": "Actual end", "schema": {"type": "date"}},
        },
    )
    # Actual start already set -> must be preserved.
    respx.get(f"{BASE}/rest/api/3/issue/PAY-2").mock(
        return_value=httpx.Response(200, json={"fields": {"customfield_1": "2026-09-01"}})
    )
    put = respx.put(f"{BASE}/rest/api/3/issue/PAY-2").mock(return_value=httpx.Response(204))

    written = apply_actual_dates(c, "PAY-2", started_at=START, ended_at=END)
    assert "customfield_1" not in written  # not overwritten
    assert "customfield_2" in written
    sent = json.loads(put.calls.last.request.read().decode())["fields"]
    assert "customfield_1" not in sent
    c.close()


@respx.mock
def test_noop_when_no_date_fields():
    c = _client()
    _editmeta(rmock=respx, key="PAY-3", fields={"summary": {"name": "Summary", "schema": {"type": "string"}}})
    written = apply_actual_dates(c, "PAY-3", started_at=START, ended_at=END)
    assert written == {}
    c.close()
