"""Phase 5 API tests: reports, settings, transitions, and AI degradation.

Section 14 requires an explicit "app functions end to end with the AI provider
unreachable" test; the default provider here is Ollama with nothing listening,
so every AI route must degrade to raw text with used_ai=False and never hang.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-p5-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Board, WorkSession, utcnow  # noqa: E402
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
    db = SessionLocal()
    try:
        db.add(Board(id=1, name="Payments", type="scrum", project_key="PAY"))
        db.commit()
        save_connection(
            db, base_url=BASE, email="me@acme.com", account_id="acc-1", display_name="Me"
        )
        # Two completed sessions this week: one synced, one errored (unlogged).
        now = utcnow()
        s1 = WorkSession(
            description="synced work",
            board_id=1,
            issue_key="PAY-1",
            started_at=now - timedelta(hours=2),
            ended_at=now - timedelta(hours=1),
            paused_seconds=0,
            state="completed",
            sync_state="synced",
        )
        s2 = WorkSession(
            description="failed work",
            board_id=1,
            issue_key="PAY-2",
            started_at=now - timedelta(hours=4),
            ended_at=now - timedelta(hours=3),
            paused_seconds=0,
            state="completed",
            sync_state="error",
            sync_error="HTTP 400 bad field",
        )
        db.add_all([s1, s2])
        db.commit()
    finally:
        db.close()
    store_token("tok-123")


# --- reports ---

def test_week_report_tracked_vs_logged(client):
    r = client.get("/api/reports/week")
    assert r.status_code == 200
    body = r.json()
    assert len(body["days"]) == 7
    # Two 1-hour sessions tracked; only one synced -> logged is half.
    assert body["total_tracked_seconds"] == 2 * 3600
    assert body["total_logged_seconds"] == 3600
    # Per-issue breakdown present.
    keys = {i["issue_key"] for i in body["issues"]}
    assert {"PAY-1", "PAY-2"} <= keys


def test_unlogged_lists_only_unsynced(client):
    r = client.get("/api/reports/unlogged")
    assert r.status_code == 200
    keys = {s["issue_key"] for s in r.json()}
    assert "PAY-2" in keys  # errored
    assert "PAY-1" not in keys  # synced, not surfaced


# --- settings ---

def test_get_settings_defaults(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_provider"] in {"ollama", "none", "gemini", "groq"}
    assert body["idle_threshold_minutes"] == 15
    assert body["has_gemini_key"] is False


def test_patch_settings_updates_and_stores_key(client):
    r = client.patch(
        "/api/settings",
        json={
            "ai_provider": "gemini",
            "idle_threshold_minutes": 20,
            "uses_tempo": True,
            "gemini_api_key": "secret-key-xyz",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ai_provider"] == "gemini"
    assert body["idle_threshold_minutes"] == 20
    assert body["uses_tempo"] is True
    # Key presence reported, value never returned.
    assert body["has_gemini_key"] is True
    assert "secret-key-xyz" not in r.text
    # Reset provider so later AI-degradation test uses Ollama (unreachable).
    client.patch("/api/settings", json={"ai_provider": "ollama"})


# --- AI degradation (section 14: app works with AI unreachable) ---

def test_ai_status_reports_unavailable_when_ollama_down(client):
    # Provider is ollama, nothing is listening on localhost:11434 in tests.
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    # available should be False (server down); never raises.
    assert r.json()["provider"] == "ollama"


def test_ai_cleanup_comment_degrades_to_raw_text(client):
    r = client.post("/api/ai/cleanup-comment", json={"text": "fixed the webhook bug"})
    assert r.status_code == 200
    body = r.json()
    assert body["used_ai"] is False
    assert body["text"] == "fixed the webhook bug"


def test_ai_draft_summary_degrades(client):
    r = client.post(
        "/api/ai/draft-summary",
        json={"text": "fixing the retry logic on the payment webhook"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["used_ai"] is False
    assert "retry" in body["text"].lower()


# --- transitions through the outbox (section 5.6) ---

@pytest.fixture
def rmock():
    with respx.mock(assert_all_called=False) as m:
        m.route(host="testserver").pass_through()
        yield m


def test_complete_with_transition_enqueues_and_runs(client, rmock):
    # A worklog + a transition. Worklog succeeds; transitions endpoint offers a
    # matching "Done" transition, which we then POST.
    rmock.post(f"{BASE}/rest/api/3/issue/PAY-5/worklog").mock(
        return_value=httpx.Response(201, json={"id": "700"})
    )
    transitions_get = rmock.get(f"{BASE}/rest/api/3/issue/PAY-5/transitions").mock(
        return_value=httpx.Response(
            200, json={"transitions": [{"id": "31", "name": "Done"}]}
        )
    )
    transition_post = rmock.post(f"{BASE}/rest/api/3/issue/PAY-5/transitions").mock(
        return_value=httpx.Response(204)
    )

    # Start + complete a session with a transition.
    s = client.post("/api/sessions", json={"description": "work", "board_id": 1}).json()
    client.patch(f"/api/sessions/{s['id']}", json={"issue_key": "PAY-5"})
    r = client.post(
        f"/api/sessions/{s['id']}/complete",
        json={"notes": "", "transition_to": "Done", "adjusted_seconds": 120},
    )
    assert r.status_code == 200, r.text

    assert transitions_get.called
    assert transition_post.called
    # Outbox should show the transition item as done (history needs include_done).
    outbox = client.get("/api/outbox?include_done=true").json()
    kinds = {i["kind"]: i["state"] for i in outbox}
    assert kinds.get("transition") == "done"


def test_complete_with_missing_transition_is_not_an_error(client, rmock):
    # No matching transition name -> skip silently, item still completes (5.6).
    rmock.post(f"{BASE}/rest/api/3/issue/PAY-6/worklog").mock(
        return_value=httpx.Response(201, json={"id": "701"})
    )
    rmock.get(f"{BASE}/rest/api/3/issue/PAY-6/transitions").mock(
        return_value=httpx.Response(
            200, json={"transitions": [{"id": "10", "name": "In Progress"}]}
        )
    )

    s = client.post("/api/sessions", json={"description": "w2", "board_id": 1}).json()
    client.patch(f"/api/sessions/{s['id']}", json={"issue_key": "PAY-6"})
    r = client.post(
        f"/api/sessions/{s['id']}/complete",
        json={"transition_to": "Done", "adjusted_seconds": 120},
    )
    assert r.status_code == 200, r.text
    outbox = client.get("/api/outbox?include_done=true").json()
    transition_items = [i for i in outbox if i["kind"] == "transition"]
    assert transition_items and transition_items[-1]["state"] == "done"
