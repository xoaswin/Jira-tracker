"""Phase-manage API tests: date edit, transitions, and the subtask-block rule,
with Jira mocked by respx."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-manage-")
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


def _editmeta(rmock, key, fields):
    rmock.get(f"{BASE}/rest/api/3/issue/{key}/editmeta").mock(
        return_value=httpx.Response(200, json={"fields": fields})
    )


def _issue(rmock, key, payload):
    rmock.get(f"{BASE}/rest/api/3/issue/{key}").mock(
        return_value=httpx.Response(200, json=payload)
    )


def test_manage_view_lists_dates_and_subtasks(client, rmock):
    _editmeta(
        rmock,
        "PAY-1",
        {
            "duedate": {"name": "Due date", "schema": {"type": "date"}},
            "customfield_10015": {"name": "Start date", "schema": {"type": "date"}},
            "summary": {"name": "Summary", "schema": {"type": "string"}},  # ignored
        },
    )
    _issue(
        rmock,
        "PAY-1",
        {
            "key": "PAY-1",
            "fields": {
                "summary": "Parent work",
                "status": {"name": "In Progress", "statusCategory": {"name": "In Progress", "key": "indeterminate"}},
                "issuetype": {"name": "Story"},
                "duedate": "2026-09-20",
                "customfield_10015": "2026-09-15",
                "subtasks": [
                    {"key": "PAY-2", "fields": {"summary": "sub a",
                     "status": {"name": "Done", "statusCategory": {"name": "Done", "key": "done"}}}},
                    {"key": "PAY-3", "fields": {"summary": "sub b",
                     "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}}}},
                ],
            },
        },
    )
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-1/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": [
            {"id": "31", "name": "Done", "to": {"name": "Done", "statusCategory": {"key": "done"}}}
        ]})
    )

    r = client.get("/api/manage/PAY-1")
    assert r.status_code == 200, r.text
    body = r.json()
    # Only the two date fields, not summary.
    ids = {f["field_id"] for f in body["date_fields"]}
    assert ids == {"duedate", "customfield_10015"}
    assert body["date_fields"][0]["value"] in ("2026-09-20", "2026-09-15")
    # Subtasks with done-ness.
    subs = {s["issue_key"]: s["is_done"] for s in body["subtasks"]}
    assert subs == {"PAY-2": True, "PAY-3": False}


def test_edit_dates_sends_only_editable_fields(client, rmock):
    _editmeta(rmock, "PAY-1", {"duedate": {"name": "Due date", "schema": {"type": "date"}}})
    put = rmock.put(f"{BASE}/rest/api/3/issue/PAY-1").mock(return_value=httpx.Response(204))
    # For the refetch after edit.
    _issue(rmock, "PAY-1", {"key": "PAY-1", "fields": {"summary": "x",
        "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
        "duedate": "2026-10-01", "subtasks": []}})
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-1/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": []}))

    r = client.patch(
        "/api/manage/PAY-1/dates",
        json={"values": {"duedate": "2026-10-01", "customfield_999": "nope"}},
    )
    assert r.status_code == 200, r.text
    import json as _json
    sent = _json.loads(put.calls.last.request.read().decode())["fields"]
    # customfield_999 is not in editmeta -> dropped; only duedate sent.
    assert sent == {"duedate": "2026-10-01"}


def test_add_worklog_posts_seconds_and_comment(client, rmock):
    # The dedup guard first GETs existing worklogs; none match -> post proceeds.
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-5/worklog").mock(
        return_value=httpx.Response(200, json={"worklogs": []})
    )
    posted = rmock.post(f"{BASE}/rest/api/3/issue/PAY-5/worklog").mock(
        return_value=httpx.Response(
            201,
            json={"id": "wl-1", "timeSpentSeconds": 5400, "started": "2026-09-18T09:00:00.000+0000"},
        )
    )
    r = client.post(
        "/api/manage/PAY-5/worklog",
        json={"hours": 1, "minutes": 30, "started": "2026-09-18T09:00", "comment": "did the thing"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["worklog"]["id"] == "wl-1"
    assert body["rounded_up"] is False

    import json as _json
    sent = _json.loads(posted.calls.last.request.read().decode())
    # 1h30m = 5400s, and the comment is sent as ADF (a dict), not raw text.
    assert sent["timeSpentSeconds"] == 5400
    assert isinstance(sent["comment"], dict)


def test_add_worklog_rejects_zero_time(client, rmock):
    r = client.post("/api/manage/PAY-5/worklog", json={"hours": 0, "minutes": 0})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "no_time"


def test_add_worklog_dedupes_recent_identical(client, rmock):
    # A worklog matching what we're about to post already exists (same author,
    # seconds, comment, ~now). The service must return it instead of posting a
    # duplicate. Connected account_id is "acc-1" (see the connect fixture).
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    rmock.get(f"{BASE}/rest/api/3/issue/PPVM-1/worklog").mock(
        return_value=httpx.Response(200, json={"worklogs": [
            {"id": "dup-1", "timeSpentSeconds": 3600, "started": now_iso,
             "author": {"accountId": "acc-1"}},
        ]})
    )
    post = rmock.post(f"{BASE}/rest/api/3/issue/PPVM-1/worklog").mock(
        return_value=httpx.Response(201, json={"id": "SHOULD-NOT-BE-CALLED"})
    )

    r = client.post("/api/manage/PPVM-1/worklog", json={"hours": 1, "minutes": 0})
    assert r.status_code == 200, r.text
    # Returned the existing worklog, and never POSTed a new one.
    assert r.json()["worklog"]["id"] == "dup-1"
    assert post.call_count == 0


def test_list_worklogs_newest_first(client, rmock):
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-6/worklog").mock(
        return_value=httpx.Response(
            200,
            json={"worklogs": [
                {"id": "a", "timeSpentSeconds": 60, "started": "2026-09-10T09:00:00.000+0000"},
                {"id": "b", "timeSpentSeconds": 120, "started": "2026-09-18T09:00:00.000+0000"},
            ]},
        )
    )
    r = client.get("/api/manage/PAY-6/worklogs")
    assert r.status_code == 200, r.text
    ids = [w["id"] for w in r.json()]
    assert ids == ["b", "a"]  # newest first


def test_manage_view_carries_assignee_and_priority(client, rmock):
    _editmeta(rmock, "PAY-7", {})
    _issue(rmock, "PAY-7", {"key": "PAY-7", "fields": {
        "summary": "p", "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
        "assignee": {"accountId": "acc-9", "displayName": "Grace Hopper"},
        "priority": {"id": "2", "name": "High"},
        "subtasks": []}})
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-7/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": []}))

    r = client.get("/api/manage/PAY-7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assignee_account_id"] == "acc-9"
    assert body["assignee_name"] == "Grace Hopper"
    assert body["priority_id"] == "2"
    assert body["priority_name"] == "High"


def test_set_assignee_puts_account_id(client, rmock):
    put = rmock.put(f"{BASE}/rest/api/3/issue/PAY-7/assignee").mock(
        return_value=httpx.Response(204))
    # Refetch after the change.
    _editmeta(rmock, "PAY-7", {})
    _issue(rmock, "PAY-7", {"key": "PAY-7", "fields": {
        "summary": "p", "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
        "assignee": {"accountId": "acc-new", "displayName": "New Person"}, "subtasks": []}})
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-7/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": []}))

    r = client.put("/api/manage/PAY-7/assignee", json={"account_id": "acc-new"})
    assert r.status_code == 200, r.text
    import json as _json
    sent = _json.loads(put.calls.last.request.read().decode())
    assert sent == {"accountId": "acc-new"}
    assert r.json()["assignee_account_id"] == "acc-new"


def test_set_priority_puts_field(client, rmock):
    put = rmock.put(f"{BASE}/rest/api/3/issue/PAY-7").mock(return_value=httpx.Response(204))
    _editmeta(rmock, "PAY-7", {})
    _issue(rmock, "PAY-7", {"key": "PAY-7", "fields": {
        "summary": "p", "status": {"name": "To Do", "statusCategory": {"name": "To Do", "key": "new"}},
        "priority": {"id": "1", "name": "Highest"}, "subtasks": []}})
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-7/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": []}))

    r = client.put("/api/manage/PAY-7/priority", json={"priority_id": "1"})
    assert r.status_code == 200, r.text
    import json as _json
    sent = _json.loads(put.calls.last.request.read().decode())
    assert sent == {"fields": {"priority": {"id": "1"}}}
    assert r.json()["priority_name"] == "Highest"


def test_assignable_users_and_priorities(client, rmock):
    rmock.get(f"{BASE}/rest/api/3/user/assignable/search").mock(
        return_value=httpx.Response(200, json=[
            {"accountId": "a1", "displayName": "Alice", "emailAddress": "a@x.com"},
        ]))
    rmock.get(f"{BASE}/rest/api/3/priority").mock(
        return_value=httpx.Response(200, json=[
            {"id": "1", "name": "Highest"}, {"id": "2", "name": "High"},
        ]))

    r = client.get("/api/manage/PAY-7/assignable", params={"q": "Ali"})
    assert r.status_code == 200, r.text
    assert r.json()[0]["display_name"] == "Alice"

    r2 = client.get("/api/manage/PAY-7/priorities")
    assert [p["name"] for p in r2.json()] == ["Highest", "High"]


def test_mark_done_blocked_when_subtask_open(client, rmock):
    # get_manage_view is called first (editmeta + issue + transitions).
    _editmeta(rmock, "PAY-10", {})
    _issue(rmock, "PAY-10", {"key": "PAY-10", "fields": {"summary": "parent",
        "status": {"name": "In Progress", "statusCategory": {"name": "In Progress", "key": "indeterminate"}},
        "subtasks": [
            {"key": "PAY-11", "fields": {"summary": "s", "status": {"name": "To Do", "statusCategory": {"key": "new"}}}},
        ]}})
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-10/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": []}))

    r = client.post("/api/manage/PAY-10/done")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "subtasks_incomplete"
    assert "PAY-11" in detail["pending_subtasks"]