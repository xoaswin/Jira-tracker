"""End-to-end Phase 1 API tests: connect -> board -> issue -> session -> push.

Runs against an isolated temp SQLite DB with Jira fully mocked by respx and a
temp file secret store. No real Jira, no real keychain (section 14).
"""

import json
import os
import re
import tempfile
from pathlib import Path

# Isolate the app onto a throwaway DB / secret store BEFORE importing app modules.
_TMP = tempfile.mkdtemp(prefix="jt-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.secrets import FileBackend, reset_secret_store_for_tests  # noqa: E402

BASE = "https://acme.atlassian.net"


@pytest.fixture(scope="module")
def client():
    # Rebind to this module's DB before the app starts (lifespan runs
    # migrations), so app-importing test modules don't share one SQLite file.
    # Use this module's own _TMP, not the shared env var (pytest imports every
    # module first, so the env var holds whichever imported last).
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    reset_secret_store_for_tests(FileBackend(Path(_TMP) / "secrets.json"))
    with TestClient(app) as c:
        yield c
    reset_secret_store_for_tests(None)


@pytest.fixture
def rmock():
    """respx router that mocks Jira but passes app (testserver) calls through."""
    with respx.mock(assert_all_called=False) as m:
        m.route(host="testserver").pass_through()
        yield m


def _connect(client, rmock):
    rmock.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "acc-1", "displayName": "Aswin"})
    )
    return client.post(
        "/api/auth/connect",
        json={"base_url": BASE, "email": "me@acme.com", "token": "tok-123"},
    )


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_connect_invalid_token_surfaces_jira_body(client, rmock):
    rmock.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(401, json={"errorMessages": ["Unauthorized"]})
    )
    r = client.post(
        "/api/auth/connect",
        json={"base_url": BASE, "email": "me@acme.com", "token": "bad"},
    )
    assert r.status_code == 400
    assert "Unauthorized" in json.dumps(r.json())


def test_boards_refresh_before_connect_is_409(client):
    # Fresh state: not connected yet.
    r = client.get("/api/boards", params={"refresh": "true"})
    assert r.status_code == 409
    assert r.json()["code"] == "not_connected"


def test_full_phase1_flow(client, rmock):
    # 1. connect
    r = _connect(client, rmock)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["account_id"] == "acc-1"

    # 2. status reflects connection
    r = client.get("/api/auth/status")
    assert r.json()["connected"] is True
    assert r.json()["display_name"] == "Aswin"

    # 3. refresh boards
    rmock.get(f"{BASE}/rest/agile/1.0/board").mock(
        return_value=httpx.Response(
            200,
            json={
                "isLast": True,
                "values": [
                    {"id": 10, "name": "Payments", "type": "scrum",
                     "location": {"type": "project", "key": "PAY", "id": 1001, "name": "Payments"}},
                ],
            },
        )
    )
    r = client.get("/api/boards", params={"refresh": "true"})
    assert r.status_code == 200
    boards = r.json()
    assert boards[0]["id"] == 10
    assert boards[0]["project_key"] == "PAY"

    # cached read (no refresh) still returns it
    assert client.get("/api/boards").json()[0]["id"] == 10

    # 4. refresh issues for the board
    rmock.get(f"{BASE}/rest/agile/1.0/board/10/issue").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "issues": [
                    {
                        "id": "20001",
                        "key": "PAY-431",
                        "fields": {
                            "summary": "Fix webhook retry backoff",
                            "description": None,
                            "issuetype": {"name": "Story"},
                            "status": {"name": "In Progress",
                                       "statusCategory": {"name": "In Progress"}},
                            "assignee": {"accountId": "acc-1"},
                            "updated": "2026-09-07T09:30:00.000+0530",
                            "project": {"key": "PAY"},
                        },
                    }
                ],
            },
        )
    )
    r = client.get("/api/boards/10/issues", params={"refresh": "true"})
    assert r.status_code == 200
    issues = r.json()
    assert issues[0]["issue_key"] == "PAY-431"

    # 5. start a session
    r = client.post("/api/sessions", json={"description": "webhook retry backoff", "board_id": 10})
    assert r.status_code == 200
    session = r.json()
    sid = session["id"]
    assert session["state"] == "active"

    # active session endpoint returns it
    assert client.get("/api/sessions/active").json()["id"] == sid

    # 6. pause and resume (exercise the pause path)
    assert client.post(f"/api/sessions/{sid}/pause").json()["state"] == "paused"
    assert client.post(f"/api/sessions/{sid}/resume").json()["state"] == "active"

    # 7. attach the matched issue
    r = client.patch(f"/api/sessions/{sid}", json={"issue_key": "PAY-431", "issue_origin": "matched"})
    assert r.json()["issue_key"] == "PAY-431"

    # 8. complete -> pushes worklog + comment
    worklog_route = rmock.post(f"{BASE}/rest/api/3/issue/PAY-431/worklog").mock(
        return_value=httpx.Response(201, json={"id": "90001"})
    )
    comment_route = rmock.post(f"{BASE}/rest/api/3/issue/PAY-431/comment").mock(
        return_value=httpx.Response(201, json={"id": "70001"})
    )
    r = client.post(
        f"/api/sessions/{sid}/complete",
        json={"notes": "Fixed the backoff. Added a jittered retry."},
    )
    assert r.status_code == 200
    result = r.json()
    assert result["session"]["state"] == "completed"
    assert result["session"]["sync_state"] == "synced"
    assert result["session"]["worklog_jira_id"] == "90001"
    assert result["session"]["comment_jira_id"] == "70001"

    # Exactly one worklog and one comment were posted.
    assert worklog_route.call_count == 1
    assert comment_route.call_count == 1

    # The worklog 'started' obeys Jira's strict format.
    wl_body = json.loads(worklog_route.calls.last.request.read().decode())
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{4}", wl_body["started"])
    assert isinstance(wl_body["timeSpentSeconds"], int)


def test_complete_without_issue_is_saved_but_flagged(client, rmock):
    _connect(client, rmock)
    r = client.post("/api/sessions", json={"description": "no ticket work", "board_id": None})
    sid = r.json()["id"]
    r = client.post(f"/api/sessions/{sid}/complete", json={"notes": "did stuff"})
    assert r.status_code == 200
    result = r.json()
    # Session is completed and NOT lost, just flagged as needing an issue.
    assert result["session"]["state"] == "completed"
    assert result["session"]["sync_state"] == "unsynced"
    assert "No issue selected" in result["warning"]


def test_complete_surfaces_jira_push_failure_without_losing_session(client, rmock):
    _connect(client, rmock)
    r = client.post("/api/sessions", json={"description": "work", "board_id": None})
    sid = r.json()["id"]
    client.patch(f"/api/sessions/{sid}", json={"issue_key": "PAY-999"})

    # A permanent 400 on the worklog. The comment is an independent outbox item
    # now (Phase 2), so mock it as succeeding; we assert the *worklog* failure is
    # what surfaces on the session (any failed item -> sync_state "error", rule 8).
    rmock.post(f"{BASE}/rest/api/3/issue/PAY-999/worklog").mock(
        return_value=httpx.Response(400, json={"errors": {"timeSpentSeconds": "bad"}})
    )
    rmock.post(f"{BASE}/rest/api/3/issue/PAY-999/comment").mock(
        return_value=httpx.Response(201, json={"id": "70099"})
    )
    r = client.post(f"/api/sessions/{sid}/complete", json={"notes": "notes"})
    assert r.status_code == 200
    result = r.json()
    assert result["session"]["state"] == "completed"
    assert result["session"]["sync_state"] == "error"
    assert "timeSpentSeconds" in result["session"]["sync_error"]


def test_manual_time_entry_pushes_worklog(client, rmock):
    """Logging past work without a timer creates a completed session and pushes a
    worklog with the given duration."""
    _connect(client, rmock)
    wl = rmock.post(f"{BASE}/rest/api/3/issue/PAY-500/worklog").mock(
        return_value=httpx.Response(201, json={"id": "5001"})
    )
    r = client.post(
        "/api/sessions/manual",
        json={
            "description": "Reviewed the migration plan yesterday",
            "duration_seconds": 3600,
            "issue_key": "PAY-500",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session"]["state"] == "completed"
    assert body["session"]["issue_origin"] == "manual"
    assert body["duration_seconds"] == 3600
    assert wl.call_count == 1
    # The pushed worklog carries the manual duration.
    sent = json.loads(wl.calls.last.request.read().decode())
    assert sent["timeSpentSeconds"] == 3600


def test_manual_entry_without_issue_is_saved_not_pushed(client, rmock):
    _connect(client, rmock)
    r = client.post(
        "/api/sessions/manual",
        json={"description": "misc admin", "duration_seconds": 600},
    )
    assert r.status_code == 200
    assert r.json()["session"]["sync_state"] == "unsynced"


def test_repush_updates_existing_worklog_no_duplicate(client, rmock):
    """Editing a synced session and re-pushing UPDATES the worklog in place (PUT),
    never creating a second one (rule 3)."""
    _connect(client, rmock)
    # First: a manual entry that syncs, giving us a worklog id.
    create_wl = rmock.post(f"{BASE}/rest/api/3/issue/PAY-600/worklog").mock(
        return_value=httpx.Response(201, json={"id": "6001"})
    )
    r = client.post(
        "/api/sessions/manual",
        json={"description": "work", "duration_seconds": 1800, "issue_key": "PAY-600"},
    )
    sid = r.json()["session"]["id"]
    assert r.json()["session"]["sync_state"] == "synced"

    # Edit the duration, then re-push. Expect a PUT to the existing worklog, and
    # NO new POST.
    put = rmock.put(f"{BASE}/rest/api/3/issue/PAY-600/worklog/6001").mock(
        return_value=httpx.Response(200, json={"id": "6001"})
    )
    client.patch(f"/api/sessions/{sid}", json={"adjusted_seconds": 7200})
    r = client.post(f"/api/sessions/{sid}/repush")
    assert r.status_code == 200, r.text
    assert put.call_count == 1
    # The worklog was created once and never re-created.
    assert create_wl.call_count == 1
    sent = json.loads(put.calls.last.request.read().decode())
    assert sent["timeSpentSeconds"] == 7200


def test_abandon_session_pushes_nothing(client, rmock):
    """Discarding a session (e.g. accidental pick) leaves without tracking:
    it is marked abandoned, no worklog/comment is enqueued, and no Jira call is
    made."""
    _connect(client, rmock)
    r = client.post("/api/sessions", json={"description": "oops wrong ticket", "board_id": None})
    sid = r.json()["id"]
    client.patch(f"/api/sessions/{sid}", json={"issue_key": "PAY-431"})

    # Register worklog/comment mocks so we can assert they are NEVER called.
    wl = rmock.post(f"{BASE}/rest/api/3/issue/PAY-431/worklog").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    cm = rmock.post(f"{BASE}/rest/api/3/issue/PAY-431/comment").mock(
        return_value=httpx.Response(201, json={"id": "2"})
    )

    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["state"] == "abandoned"

    # Nothing was pushed, and nothing sits in the outbox for this session.
    assert wl.call_count == 0
    assert cm.call_count == 0
    # The session no longer shows as active.
    assert client.get("/api/sessions/active").json() is None


def test_disconnect_clears_state(client, rmock):
    _connect(client, rmock)
    assert client.get("/api/auth/status").json()["connected"] is True
    assert client.delete("/api/auth").status_code == 204
    assert client.get("/api/auth/status").json()["connected"] is False
