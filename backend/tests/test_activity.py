"""Activity recorder: ticket inference, merging, zero-click tracking with undo,
away-pausing, the day timeline and the focus radar."""

import os
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-activity-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ActivitySegment, AppSettings, Issue, WorkSession, utcnow  # noqa: E402
from app.secrets import FileBackend, reset_secret_store_for_tests  # noqa: E402
from app.services import activity  # noqa: E402


@pytest.fixture(scope="module")
def client():
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    reset_secret_store_for_tests(FileBackend(Path(_TMP) / "secrets.json"))
    with TestClient(app) as c:
        db = SessionLocal()
        db.add(Issue(jira_id="1", issue_key="PPVM-123", project_key="PPVM", summary="Fix retries"))
        db.add(Issue(jira_id="2", issue_key="PPVM-9", project_key="PPVM", summary="Other"))
        s = db.get(AppSettings, 1)
        s.work_start_time, s.work_end_time = None, None  # always "in hours" for tests
        db.commit()
        db.close()
        yield c
    reset_secret_store_for_tests(None)


@pytest.fixture(autouse=True)
def clean(client):
    activity.reset_state_for_tests()
    db = SessionLocal()
    db.query(ActivitySegment).delete()
    db.query(WorkSession).delete()
    db.commit()
    db.close()


def _seg(start, minutes, app="chrome", title="", kind="active"):
    return {"start": start.isoformat(), "end": (start + timedelta(minutes=minutes)).isoformat(),
            "app": app, "title": title, "kind": kind}


def test_key_from_title_only_for_known_projects(client):
    db = SessionLocal()
    try:
        assert activity.infer_key(db, "chrome", "[PPVM-123] Fix retries - Jira") == ("PPVM-123", "title")
        assert activity.infer_key(db, "code", "ppvm-123-fix-retries - repo - Visual Studio Code")[0] == "PPVM-123"
        assert activity.infer_key(db, "notepad", "UTF-8 encoding notes") == (None, None)
    finally:
        db.close()


def test_key_from_editor_repo_branch(client, tmp_path):
    repo = tmp_path / "payments-api"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    run("checkout", "-q", "-b", "feature/PPVM-9-retry")
    db = SessionLocal()
    try:
        db.get(AppSettings, 1).git_repo_paths = [str(repo)]
        db.commit()
        key = activity.infer_key(db, "Code", "handler.py - payments-api [WSL: Ubuntu] - Visual Studio Code")
        assert key == ("PPVM-9", "branch")
        db.get(AppSettings, 1).git_repo_paths = []
        db.commit()
    finally:
        db.close()


def test_segments_merge_when_same_window(client):
    t0 = utcnow() - timedelta(minutes=30)
    client.post("/api/activity/segments", json={"segments": [_seg(t0, 1, title="A")]})
    client.post("/api/activity/segments", json={"segments": [_seg(t0 + timedelta(minutes=1, seconds=5), 1, title="A")]})
    client.post("/api/activity/segments", json={"segments": [_seg(t0 + timedelta(minutes=2, seconds=5), 1, title="B")]})
    db = SessionLocal()
    try:
        rows = db.query(ActivitySegment).order_by(ActivitySegment.started_at).all()
        assert [r.title for r in rows] == ["A", "B"]
        assert (rows[0].ended_at - rows[0].started_at) > timedelta(minutes=1, seconds=59)
    finally:
        db.close()


def test_autotrack_starts_after_dwell_then_undo_suppresses(client):
    now = utcnow()
    r = client.post("/api/activity/segments", json={"segments": [
        _seg(now - timedelta(minutes=6), 6, title="PPVM-123 Fix retries - Jira"),
    ]}).json()
    assert r["suggestion"]["action"] == "start" and r["suggestion"]["issue_key"] == "PPVM-123"

    started = client.post("/api/activity/autotrack", json={"issue_key": "PPVM-123"}).json()
    assert started["changed"] and started["previous"] is None
    db = SessionLocal()
    try:
        s = db.get(WorkSession, started["session_id"])
        assert s.issue_origin == "auto" and s.description == "Fix retries"
    finally:
        db.close()
    # Already on it: nothing more to suggest.
    assert client.post("/api/activity/segments", json={"segments": []}).json()["suggestion"] is None

    undo = client.post("/api/activity/autotrack/undo", json={"session_id": started["session_id"]}).json()
    assert undo["ok"]
    # Suppressed after undo even though the ticket still dominates.
    assert client.post("/api/activity/segments", json={"segments": []}).json()["suggestion"] is None


def test_brief_glance_does_not_trigger(client):
    now = utcnow()
    r = client.post("/api/activity/segments", json={"segments": [
        _seg(now - timedelta(minutes=6), 5, app="outlook", title="Inbox"),
        _seg(now - timedelta(minutes=1), 1, title="PPVM-123 - Jira"),
    ]}).json()
    assert r["suggestion"] is None


def test_switch_needs_an_established_session(client):
    db = SessionLocal()
    s = WorkSession(description="x", issue_key="PPVM-9", started_at=utcnow() - timedelta(minutes=2),
                    state="active", paused_seconds=0)
    db.add(s)
    db.commit()
    db.close()
    now = utcnow()
    body = {"segments": [_seg(now - timedelta(minutes=6), 6, title="PPVM-123 - Jira")]}
    assert client.post("/api/activity/segments", json=body).json()["suggestion"] is None  # too young

    db = SessionLocal()
    db.query(WorkSession).update({"started_at": utcnow() - timedelta(minutes=20)})
    db.commit()
    db.close()
    sug = client.post("/api/activity/segments", json={"segments": []}).json()["suggestion"]
    assert sug == {"action": "switch", "issue_key": "PPVM-123", "share": 1.0, "from_issue_key": "PPVM-9"}

    res = client.post("/api/activity/autotrack", json={"issue_key": "PPVM-123"}).json()
    assert res["previous"]["issue_key"] == "PPVM-9"
    db = SessionLocal()
    try:
        states = {w.issue_key: w.state for w in db.query(WorkSession).all()}
        assert states == {"PPVM-9": "completed", "PPVM-123": "active"}
    finally:
        db.close()


def test_auto_track_off_means_no_suggestions(client):
    db = SessionLocal()
    db.get(AppSettings, 1).auto_track = False
    db.commit()
    db.close()
    now = utcnow()
    r = client.post("/api/activity/segments", json={"segments": [_seg(now - timedelta(minutes=6), 6, title="PPVM-123")]})
    assert r.json()["suggestion"] is None
    db = SessionLocal()
    db.get(AppSettings, 1).auto_track = True
    db.commit()
    db.close()


def test_away_pauses_and_resumes_only_what_it_paused(client):
    db = SessionLocal()
    s = WorkSession(description="x", started_at=utcnow() - timedelta(minutes=30), state="active", paused_seconds=0)
    db.add(s)
    db.commit()
    sid = s.id
    db.close()
    assert client.post("/api/activity/away", json={"away": True}).json() == {"paused": sid}
    assert client.post("/api/activity/away", json={"away": False}).json() == {"resumed": sid}
    # A manual pause is not undone by coming back.
    client.post(f"/api/sessions/{sid}/pause")
    assert client.post("/api/activity/away", json={"away": True}).json() == {"paused": None}
    assert client.post("/api/activity/away", json={"away": False}).json() == {"resumed": None}


def test_timeline_and_focus(client):
    now = utcnow()
    segs = [_seg(now - timedelta(minutes=70), 40, app="Code", title="PPVM-123 - Visual Studio Code"),
            _seg(now - timedelta(minutes=30), 1, app="ms-teams", title="Chat"),
            _seg(now - timedelta(minutes=29), 10, app="Code", title="PPVM-123 - Visual Studio Code"),
            _seg(now - timedelta(minutes=19), 10, kind="locked")]
    client.post("/api/activity/segments", json={"segments": segs})
    tl = client.get("/api/activity/day").json()
    cats = [b["category"] for b in tl["activity"]]
    assert "code" in cats and "meeting" in cats and "away" in cats
    assert tl["recording"] is True

    focus = client.get("/api/activity/focus?days=1").json()
    day = focus["days"][-1]
    # 40m + (1m Teams glance bridged) + 10m on PPVM-123 = one deep block.
    assert day["deep_blocks"] == 1 and day["longest_deep_seconds"] >= 50 * 60
    assert focus["tips"]
