"""Insights, reconciliation, and export API tests (local, no Jira)."""

import os
import tempfile
from datetime import timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-ins-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Issue, WorkSession, utcnow  # noqa: E402
from app.secrets import FileBackend, reset_secret_store_for_tests  # noqa: E402


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
        db.query(WorkSession).delete()
        db.query(Issue).delete()
        db.add(Issue(jira_id="1", issue_key="PAY-1", project_key="PAY", issue_type="Bug"))
        db.add(Issue(jira_id="2", issue_key="PAY-2", project_key="PAY", issue_type="Story"))
        db.add(Issue(jira_id="3", issue_key="GTW-9", project_key="GTW", issue_type="Task"))
        now = utcnow()
        # Three completed sessions today, distinct tickets/types/projects.
        for key, secs, synced in [
            ("PAY-1", 3600, True),
            ("PAY-2", 7200, False),
            ("GTW-9", 1800, True),
        ]:
            start = now - timedelta(seconds=secs + 60)
            db.add(
                WorkSession(
                    description=f"work {key}",
                    issue_key=key,
                    started_at=start,
                    ended_at=start + timedelta(seconds=secs),
                    paused_seconds=0,
                    state="completed",
                    sync_state="synced" if synced else "unsynced",
                )
            )
        db.commit()
    finally:
        db.close()


def test_insights_totals_and_breakdowns(client):
    r = client.get("/api/insights", params={"preset": "week"})
    assert r.status_code == 200, r.text
    body = r.json()
    # 3600 + 7200 + 1800 = 12600 tracked; only the two synced count as logged.
    assert body["total_tracked_seconds"] == 12600
    assert body["total_logged_seconds"] == 3600 + 1800
    assert body["session_count"] == 3
    assert body["ticket_count"] == 3
    projects = {b["key"]: b["tracked_seconds"] for b in body["by_project"]}
    assert projects["PAY"] == 3600 + 7200
    assert projects["GTW"] == 1800
    types = {b["key"] for b in body["by_type"]}
    assert {"Bug", "Story", "Task"} <= types


def test_insights_by_ticket_sorted_desc(client):
    body = client.get("/api/insights", params={"preset": "week"}).json()
    tracked = [b["tracked_seconds"] for b in body["by_ticket"]]
    assert tracked == sorted(tracked, reverse=True)
    assert body["by_ticket"][0]["key"] == "PAY-2"  # largest (7200)


def test_reconcile_flags_time_without_commits(client):
    # No git repos configured in this test env -> commits map is empty, so every
    # ticket with logged time is flagged time_no_commits.
    r = client.get("/api/reconcile", params={"preset": "week"})
    assert r.status_code == 200, r.text
    rows = {row["issue_key"]: row for row in r.json()["rows"]}
    assert rows["PAY-1"]["flag"] == "time_no_commits"
    assert rows["PAY-1"]["logged_seconds"] == 3600
    assert rows["PAY-1"]["commit_count"] == 0


def test_timesheet_csv_download(client):
    r = client.get("/api/export/timesheet.csv", params={"preset": "week"})
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("date,started_at_utc,issue_key")
    assert len(lines) == 1 + 3  # header + 3 sessions
    assert any("PAY-1" in ln for ln in lines[1:])


def test_backup_downloads_sqlite_file(client):
    r = client.get("/api/export/backup")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/octet-stream"
    # SQLite files start with this magic header.
    assert r.content[:16].startswith(b"SQLite format 3")
