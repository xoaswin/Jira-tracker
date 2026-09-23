"""Phase 4 API tests: /api/issues/draft and /api/issues with Jira mocked.

Covers the createmeta discovery, the duplicate guard, required-field surfacing,
story creation, and subtask creation with a parent. No real Jira (section 14).
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-create-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Board  # noqa: E402
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
def seed(client):
    """A connected app with one board resolved to project PAY."""
    db = SessionLocal()
    try:
        db.add(Board(id=1, name="Payments", type="scrum", project_key="PAY"))
        db.commit()
        save_connection(
            db, base_url=BASE, email="me@acme.com", account_id="acc-1", display_name="Me"
        )
    finally:
        db.close()
    store_token("tok-123")


@pytest.fixture
def rmock():
    with respx.mock(assert_all_called=False) as m:
        m.route(host="testserver").pass_through()
        yield m


def _mock_createmeta(rmock, *, issue_types, required_fields_by_type=None):
    """Mock the two createmeta endpoints for project PAY."""
    rmock.get(f"{BASE}/rest/api/3/issue/createmeta/PAY/issuetypes").mock(
        return_value=httpx.Response(200, json={"issueTypes": issue_types})
    )
    required_fields_by_type = required_fields_by_type or {}
    for it in issue_types:
        fields = required_fields_by_type.get(it["id"], [])
        rmock.get(
            f"{BASE}/rest/api/3/issue/createmeta/PAY/issuetypes/{it['id']}"
        ).mock(return_value=httpx.Response(200, json={"fields": fields}))


def _mock_project_search_empty(rmock):
    rmock.get(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": [], "isLast": True})
    )


def test_draft_story_no_duplicates(client, rmock):
    _mock_createmeta(
        rmock,
        issue_types=[{"id": "10001", "name": "Story", "subtask": False}],
    )
    _mock_project_search_empty(rmock)

    r = client.post(
        "/api/issues/draft",
        json={"board_id": 1, "text": "fixing the retry logic on the payment webhook"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_key"] == "PAY"
    assert body["issue_type"] == "Story"
    assert body["summary"].lower().startswith("fixing the retry")
    assert body["required_fields"] == []
    assert body["duplicate"] is None


def test_draft_surfaces_required_custom_field(client, rmock):
    _mock_createmeta(
        rmock,
        issue_types=[{"id": "10001", "name": "Story", "subtask": False}],
        required_fields_by_type={
            "10001": [
                # auto-filled -> must be dropped
                {"fieldId": "summary", "name": "Summary", "required": True,
                 "schema": {"type": "string"}},
                # a real required custom field -> must surface
                {"fieldId": "customfield_10050", "name": "Team", "required": True,
                 "schema": {"type": "option"},
                 "allowedValues": [{"id": "1", "value": "Payments"}]},
                # not required -> must be ignored
                {"fieldId": "customfield_10099", "name": "Optional", "required": False,
                 "schema": {"type": "string"}},
            ]
        },
    )
    _mock_project_search_empty(rmock)

    r = client.post("/api/issues/draft", json={"board_id": 1, "text": "new work"})
    body = r.json()
    ids = [f["field_id"] for f in body["required_fields"]]
    assert ids == ["customfield_10050"]
    assert body["required_fields"][0]["allowed_values"][0]["value"] == "Payments"


def test_draft_duplicate_guard_blocks_above_threshold(client, rmock):
    _mock_createmeta(
        rmock,
        issue_types=[{"id": "10001", "name": "Story", "subtask": False}],
    )
    # The project search returns a near-identical existing issue.
    rmock.get(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "id": "50001",
                        "key": "PAY-431",
                        "fields": {
                            "summary": "Fix webhook retry backoff",
                            "description": None,
                            "issuetype": {"name": "Story"},
                            "status": {"name": "To Do", "statusCategory": {"name": "To Do"}},
                            "project": {"key": "PAY"},
                        },
                    }
                ],
                "isLast": True,
            },
        )
    )

    r = client.post(
        "/api/issues/draft",
        json={"board_id": 1, "text": "fix webhook retry backoff"},
    )
    body = r.json()
    assert body["duplicate"] is not None
    assert body["duplicate"]["issue_key"] == "PAY-431"
    assert body["duplicate"]["similarity"] >= 0.8


def test_create_story_end_to_end(client, rmock):
    created_key = "PAY-900"
    create_route = rmock.post(f"{BASE}/rest/api/3/issue").mock(
        return_value=httpx.Response(201, json={"id": "60001", "key": created_key})
    )
    rmock.get(f"{BASE}/rest/api/3/issue/{created_key}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "60001",
                "key": created_key,
                "fields": {
                    "summary": "Add a metrics panel",
                    "description": None,
                    "issuetype": {"name": "Story"},
                    "status": {"name": "To Do", "statusCategory": {"name": "To Do"}},
                    "project": {"key": "PAY"},
                },
            },
        )
    )

    r = client.post(
        "/api/issues",
        json={
            "board_id": 1,
            "project_key": "PAY",
            "type": "Story",
            "summary": "Add a metrics panel",
            "description": "We need a metrics panel on the dashboard.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["issue_key"] == created_key
    assert body["issue"]["issue_key"] == created_key
    assert create_route.call_count == 1

    # The create payload used ADF for description and the right project/type.
    sent = create_route.calls.last.request
    import json as _json
    payload = _json.loads(sent.read().decode())["fields"]
    assert payload["project"] == {"key": "PAY"}
    assert payload["issuetype"] == {"name": "Story"}
    assert payload["description"]["type"] == "doc"

    # And it is now in the local cache (matchable).
    issues = client.get("/api/boards/1/issues").json()
    assert any(i["issue_key"] == created_key for i in issues)


def test_create_subtask_requires_parent(client, rmock):
    # No parent_key -> 400 before any Jira call.
    r = client.post(
        "/api/issues",
        json={
            "board_id": 1,
            "project_key": "PAY",
            "type": "Sub-task",
            "summary": "child work",
            "description": "d",
        },
    )
    assert r.status_code == 400
    assert "parent" in r.json()["detail"].lower()


def test_create_subtask_with_parent(client, rmock):
    created_key = "PAY-901"
    create_route = rmock.post(f"{BASE}/rest/api/3/issue").mock(
        return_value=httpx.Response(201, json={"id": "60002", "key": created_key})
    )
    rmock.get(f"{BASE}/rest/api/3/issue/{created_key}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "60002",
                "key": created_key,
                "fields": {
                    "summary": "child work",
                    "description": None,
                    "issuetype": {"name": "Sub-task"},
                    "parent": {"key": "PAY-431"},
                    "status": {"name": "To Do", "statusCategory": {"name": "To Do"}},
                    "project": {"key": "PAY"},
                },
            },
        )
    )

    r = client.post(
        "/api/issues",
        json={
            "board_id": 1,
            "project_key": "PAY",
            "type": "Sub-task",
            "summary": "child work",
            "description": "d",
            "parent_key": "PAY-431",
        },
    )
    assert r.status_code == 200, r.text
    import json as _json
    payload = _json.loads(create_route.calls.last.request.read().decode())["fields"]
    assert payload["parent"] == {"key": "PAY-431"}
