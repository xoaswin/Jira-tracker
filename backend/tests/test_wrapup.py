"""End-of-day wrap-up: today's sessions (app timezone), drafts, and logging."""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-wrap-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.models import WorkSession  # noqa: E402
from app.secrets import FileBackend, reset_secret_store_for_tests  # noqa: E402
from app.services import wrapup as wrapup_service  # noqa: E402
from app.services.tz import (  # noqa: E402
    day_bounds,
    today as local_today,  # noqa: E402
    zone,
)


@pytest.fixture(scope="module")
def client():
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    reset_secret_store_for_tests(FileBackend(Path(_TMP) / "secrets.json"))
    with TestClient(app) as c:
        yield c
    reset_secret_store_for_tests(None)


def _ist_today_at(hour: int) -> datetime:
    ist = zone("Asia/Kolkata")
    start, _ = day_bounds(local_today(ist), local_today(ist), ist)
    return start + timedelta(hours=hour)


@pytest.fixture(scope="module")
def ids(client):
    db = SessionLocal()
    try:
        def add(**kw):
            s = WorkSession(description=kw.pop("description", "work"), paused_seconds=0,
                            state="completed", **kw)
            db.add(s)
            db.commit()
            return s.id

        ids = {
            "synced": add(issue_key="PAY-1", started_at=_ist_today_at(1),
                          ended_at=_ist_today_at(2), sync_state="synced",
                          worklog_jira_id="10", notes="done"),
            "unsynced": add(issue_key="PAY-2", started_at=_ist_today_at(3),
                            ended_at=_ist_today_at(4), sync_state="error",
                            notes="rough notes"),
            "noissue": add(started_at=_ist_today_at(5), ended_at=_ist_today_at(5) + timedelta(minutes=30),
                           sync_state="unsynced"),
            # 2 minutes before IST midnight: yesterday in IST, excluded.
            "yesterday": add(issue_key="PAY-3", started_at=_ist_today_at(0) - timedelta(minutes=2),
                             ended_at=_ist_today_at(0) - timedelta(minutes=1), sync_state="unsynced"),
        }
        return ids
    finally:
        db.close()


def test_today_lists_only_ist_today_with_totals(client, ids):
    r = client.get("/api/wrapup/today")
    assert r.status_code == 200
    body = r.json()
    got = [s["id"] for s in body["sessions"]]
    assert got == [ids["synced"], ids["unsynced"], ids["noissue"]]
    assert body["tracked_seconds"] == 3600 + 3600 + 1800
    assert body["logged_seconds"] == 3600


def test_draft_falls_back_to_notes_without_git(client, ids):
    r = client.post(f"/api/wrapup/draft/{ids['unsynced']}")
    assert r.status_code == 200
    assert r.json() == {"text": "rough notes", "used_ai": False, "source": "notes", "commit_count": 0}
    assert client.post("/api/wrapup/draft/999999").status_code == 404


def test_log_skips_synced_needs_ticket_and_pushes_the_rest(client, ids, monkeypatch):
    pushed = []

    def fake_repush(db, s):
        pushed.append(s.id)
        s.sync_state = "synced"
        db.commit()
        return {"status": "synced"}

    monkeypatch.setattr(wrapup_service, "repush_session", fake_repush)
    r = client.post("/api/wrapup/log", json={"items": [
        {"session_id": ids["synced"]},
        {"session_id": ids["unsynced"], "notes": "Fixed webhook retries"},
        {"session_id": ids["noissue"]},
    ]})
    assert r.status_code == 200
    out = {o["session_id"]: o for o in r.json()}
    assert out[ids["synced"]]["message"] == "Already logged."
    assert out[ids["unsynced"]]["ok"] and out[ids["unsynced"]]["sync_state"] == "synced"
    assert not out[ids["noissue"]]["ok"]
    assert pushed == [ids["unsynced"]]

    db = SessionLocal()
    try:
        assert db.get(WorkSession, ids["unsynced"]).notes == "Fixed webhook retries"
    finally:
        db.close()


def test_log_refuses_to_move_a_synced_worklog(client, ids):
    r = client.post("/api/wrapup/log", json={"items": [
        {"session_id": ids["synced"], "issue_key": "pay-99"},
    ]})
    assert r.json()[0]["ok"] is False

