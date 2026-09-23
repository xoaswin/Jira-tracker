"""My Tickets API test: assignee=currentUser() search + due-date urgency.

Jira mocked with respx. The urgency classification is exercised via the pure
service test in test_my_tickets.py; this asserts the endpoint wires up and
returns the buckets.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-myt-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.secrets import FileBackend, reset_secret_store_for_tests  # noqa: E402
from app.services.connection import save_connection, store_token  # noqa: E402

BASE = "https://acme.atlassian.net"


@pytest.fixture(scope="module")
def client():
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    reset_secret_store_for_tests(FileBackend(Path(_TMP) / "secrets.json"))
    with TestClient(app) as c:
        yield c
    reset_secret_store_for_tests(None)


@pytest.fixture(scope="module", autouse=True)
def connect(client):
    db = SessionLocal()
    try:
        save_connection(db, base_url=BASE, email="me@acme.com", account_id="acc-1", display_name="Me")
    finally:
        db.close()
    store_token("tok-123")


@pytest.fixture
def rmock():
    with respx.mock(assert_all_called=False) as m:
        m.route(host="testserver").pass_through()
        yield m


def test_my_tickets_returns_urgency_buckets(client, rmock):
    # Two overdue-looking, one far future, one no due date. Exact urgency depends
    # on "today", so we assert structure + that overdue is detected for a clearly
    # past date and none for a clearly future one.
    rmock.get(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    {"key": "PAY-1", "fields": {
                        "summary": "overdue one", "duedate": "2000-01-01",
                        "status": {"name": "In Progress", "statusCategory": {"name": "In Progress", "key": "indeterminate"}},
                        "issuetype": {"name": "Story"}, "priority": {"name": "High"},
                        "project": {"key": "PAY"}}},
                    {"key": "PAY-2", "fields": {
                        "summary": "far future", "duedate": "2999-12-31",
                        "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
                        "issuetype": {"name": "Task"}, "project": {"key": "PAY"}}},
                    {"key": "PAY-3", "fields": {
                        "summary": "no due date",
                        "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
                        "issuetype": {"name": "Bug"}, "project": {"key": "PAY"}}},
                ],
                "isLast": True,
            },
        )
    )

    r = client.get("/api/my-tickets")
    assert r.status_code == 200, r.text
    body = r.json()
    by_key = {t["issue_key"]: t for t in body["tickets"]}
    assert by_key["PAY-1"]["urgency"] == "overdue"
    assert by_key["PAY-1"]["priority"] == "High"
    assert by_key["PAY-2"]["urgency"] == "scheduled"
    assert by_key["PAY-3"]["urgency"] == "no_due"
    assert body["overdue"] >= 1
    # Overdue must sort before scheduled/no_due.
    assert body["tickets"][0]["issue_key"] == "PAY-1"


def test_my_tickets_sends_currentuser_jql(client, rmock):
    route = rmock.get(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": [], "isLast": True})
    )
    r = client.get("/api/my-tickets")
    assert r.status_code == 200
    sent_url = str(route.calls.last.request.url)
    assert "currentUser" in sent_url
    assert "statusCategory" in sent_url


def _plan_issues():
    return {
        "issues": [
            {"key": "PAY-1", "fields": {
                "summary": "overdue high", "duedate": "2000-01-01",
                "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
                "issuetype": {"name": "Bug"}, "priority": {"name": "High"},
                "project": {"key": "PAY"}}},
            {"key": "PAY-2", "fields": {
                "summary": "far future low", "duedate": "2999-12-31",
                "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
                "issuetype": {"name": "Story"}, "priority": {"name": "Low"},
                "project": {"key": "PAY"}}},
        ],
        "isLast": True,
    }


def test_plan_today_orders_and_fits_capacity(client, rmock):
    rmock.get(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json=_plan_issues())
    )
    # No local history -> default 1h estimate each; 6h capacity fits both.
    r = client.get("/api/plan/today", params={"capacity_hours": 6})
    assert r.status_code == 200, r.text
    body = r.json()
    keys = [i["ticket"]["issue_key"] for i in body["items"]]
    # Overdue ticket ranks first regardless of priority.
    assert keys[0] == "PAY-1"
    assert all(i["fits"] for i in body["items"])
    assert body["planned_seconds"] == 2 * 3600
    assert body["overflow_seconds"] == 0


def test_plan_today_marks_overflow_when_capacity_tight(client, rmock):
    rmock.get(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json=_plan_issues())
    )
    # 1h capacity, 1h estimates -> first fits, second overflows.
    r = client.get("/api/plan/today", params={"capacity_hours": 1})
    body = r.json()
    assert body["items"][0]["fits"] is True
    assert body["items"][1]["fits"] is False
    assert body["overflow_seconds"] == 3600
    assert body["fitted_count"] == 1


def test_velocity_estimate_defaults_without_history(client):
    # No completed sessions in this module's DB -> default 1h, based_on "default".
    r = client.get("/api/velocity/estimate", params={"issue_type": "Bug"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estimate_seconds"] == 3600
    assert body["based_on"] == "default"
    assert body["sample_count"] == 0
