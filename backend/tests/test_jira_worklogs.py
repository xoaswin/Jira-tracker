"""Tests for worklog payload building and posting."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import respx

from app.jira.worklogs import (
    add_worklog,
    build_worklog_payload,
    get_worklogs,
    normalize_time_spent,
)
from tests.conftest import BASE_URL

IST = timezone(timedelta(hours=5, minutes=30))


def test_normalize_time_spent_rounds_up_below_minimum():
    assert normalize_time_spent(30) == (60, True)
    assert normalize_time_spent(59) == (60, True)


def test_normalize_time_spent_leaves_valid_values():
    assert normalize_time_spent(60) == (60, False)
    assert normalize_time_spent(3600) == (3600, False)


def test_build_worklog_payload_exact_started_format():
    started = datetime(2026, 9, 7, 9, 30, 0, tzinfo=IST)
    payload = build_worklog_payload(started, 3600, "did the work")
    assert payload["started"] == "2026-09-07T09:30:00.000+0530"
    assert payload["timeSpentSeconds"] == 3600
    assert "timeSpent" not in payload  # never send both
    # comment must be ADF, not a plain string
    assert payload["comment"]["type"] == "doc"


def test_build_worklog_payload_omits_empty_comment():
    started = datetime(2026, 9, 7, 9, 30, 0, tzinfo=IST)
    payload = build_worklog_payload(started, 120, None)
    assert "comment" not in payload


def test_build_worklog_payload_rounds_short_session():
    started = datetime(2026, 9, 7, 9, 30, 0, tzinfo=IST)
    payload = build_worklog_payload(started, 15)
    assert payload["timeSpentSeconds"] == 60


@respx.mock
def test_add_worklog_posts_and_returns_id(jira_client):
    route = respx.post(f"{BASE_URL}/rest/api/3/issue/PAY-431/worklog").mock(
        return_value=httpx.Response(201, json={"id": "90001", "timeSpentSeconds": 3600})
    )
    started = datetime(2026, 9, 7, 9, 30, 0, tzinfo=IST)
    result = add_worklog(jira_client, "PAY-431", started, 3600, "notes")
    assert result["id"] == "90001"

    body = json.loads(route.calls.last.request.read().decode())
    assert body["timeSpentSeconds"] == 3600
    assert body["started"] == "2026-09-07T09:30:00.000+0530"


@respx.mock
def test_get_worklogs(jira_client):
    respx.get(f"{BASE_URL}/rest/api/3/issue/PAY-431/worklog").mock(
        return_value=httpx.Response(200, json={"worklogs": [{"id": "1"}, {"id": "2"}]})
    )
    logs = get_worklogs(jira_client, "PAY-431")
    assert [w["id"] for w in logs] == ["1", "2"]
