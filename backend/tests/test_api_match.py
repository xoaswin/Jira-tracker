"""Phase 3 API tests: /api/match and /api/git/context.

Reuses the isolated-DB pattern from the Phase 1 API test. Jira is mocked with
respx; matching itself never calls Jira. Embeddings are left disabled (the model
is not installed in CI), so these assert the BM25 + recency + key-extraction
path, which is the always-on core.
"""

import os
import subprocess
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-match-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppSettings, Board, Issue, utcnow  # noqa: E402
from app.secrets import FileBackend, reset_secret_store_for_tests  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # Isolate this module's DB before the app starts (see test_api_phase1).
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    reset_secret_store_for_tests(FileBackend(Path(_TMP) / "secrets.json"))
    with TestClient(app) as c:
        yield c
    reset_secret_store_for_tests(None)


@pytest.fixture(scope="module", autouse=True)
def seed_data(client):
    """Two boards with distinct open issues, for single and multi-board tests."""
    db = SessionLocal()
    try:
        db.add(Board(id=1, name="Payments", type="scrum", project_key="PAY"))
        db.add(Board(id=2, name="Gateway", type="scrum", project_key="GTW"))
        issues = [
            # board 1
            (1, "10001", "PAY-431", "Fix webhook retry backoff", "the payment webhook retries too fast", "Story"),
            (1, "10002", "PAY-99", "Login page CSS tweak", "align the login button", "Bug"),
            (1, "10003", "PAY-200", "Database migration for invoices", "add invoice table", "Task"),
            (1, "10004", "PAY-777", "Webhook signature verification", "verify hmac on inbound webhooks", "Sub-task"),
            # board 2
            (2, "20001", "GTW-5", "Gateway timeout on upstream", "requests to upstream time out", "Story"),
            (2, "20002", "GTW-8", "Webhook delivery retries", "retry webhook delivery on failure", "Story"),
        ]
        for board_id, jira_id, key, summary, desc, itype in issues:
            db.add(
                Issue(
                    jira_id=jira_id,
                    issue_key=key,
                    board_id=board_id,
                    project_key=key.split("-")[0],
                    issue_type=itype,
                    summary=summary,
                    description_text=desc,
                    status="To Do",
                    status_category="To Do",
                    updated_at=utcnow(),
                )
            )
        db.commit()
    finally:
        db.close()


def test_match_surfaces_right_ticket_top(client):
    r = client.post("/api/match", json={"board_id": 1, "text": "webhook retry backoff"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"], "expected ranked candidates"
    assert body["candidates"][0]["issue_key"] == "PAY-431"
    # At most the top 3 are returned (section 6).
    assert len(body["candidates"]) <= 3
    # Embeddings are not installed in CI; the core path still works.
    assert body["used_embeddings"] is False


def test_match_explicit_key_forces_top(client):
    r = client.post("/api/match", json={"board_id": 1, "text": "log time against PAY-200 please"})
    body = r.json()
    assert body["forced_key"] == "PAY-200"
    assert body["candidates"][0]["issue_key"] == "PAY-200"
    assert body["candidates"][0]["confidence_pct"] == 100
    assert body["preselect_top"] is True


def test_match_branch_key_preselects(client):
    r = client.post(
        "/api/match",
        json={"board_id": 1, "text": "some signature work", "branch_key": "PAY-777"},
    )
    body = r.json()
    assert body["forced_key"] == "PAY-777"
    assert body["candidates"][0]["issue_key"] == "PAY-777"


def test_match_unknown_board_404(client):
    r = client.post("/api/match", json={"board_id": 999, "text": "anything"})
    assert r.status_code == 404


# --- multi-board (pinned) search ---

def test_match_across_multiple_boards(client):
    # "webhook" appears on both boards; searching both should surface candidates
    # from each, and report both boards as searched.
    r = client.post(
        "/api/match",
        json={"board_ids": [1, 2], "text": "webhook retry delivery"},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["searched_board_ids"]) == {1, 2}
    keys = {c["issue_key"] for c in body["candidates"]}
    # At least one candidate from each board's webhook-related issue.
    assert keys & {"PAY-431", "GTW-8"}


def test_match_board_ids_takes_precedence_over_board_id(client):
    r = client.post(
        "/api/match",
        json={"board_id": 1, "board_ids": [2], "text": "gateway timeout"},
    )
    body = r.json()
    assert body["searched_board_ids"] == [2]
    assert body["candidates"][0]["issue_key"] == "GTW-5"


def test_match_all_issue_types_are_candidates(client):
    # A description matching a Bug/Task/Sub-task must still be rankable, not just
    # Stories: matching does not filter by issue type.
    r = client.post("/api/match", json={"board_id": 1, "text": "align login button css"})
    body = r.json()
    assert body["candidates"][0]["issue_key"] == "PAY-99"  # a Bug
    assert body["candidates"][0]["issue_type"] == "Bug"


def test_match_requires_a_board(client):
    r = client.post("/api/match", json={"text": "no board given"})
    assert r.status_code == 400


def test_match_dedup_when_boards_overlap(client):
    # Passing the same board twice must not double-count its issues.
    r = client.post("/api/match", json={"board_ids": [1, 1], "text": "webhook"})
    body = r.json()
    assert body["searched_board_ids"] == [1]


def test_match_surfaces_assignee_and_is_mine(client):
    # Assign PAY-431 to the connected user and PAY-99 to someone else, then match.
    db = SessionLocal()
    try:
        settings = db.get(AppSettings, 1) or AppSettings(id=1)
        settings.account_id = "me-123"
        db.merge(settings)
        for key, acct, name in [
            ("PAY-431", "me-123", "Me Myself"),
            ("PAY-99", "other-456", "Colleague Carol"),
        ]:
            issue = db.query(Issue).filter(Issue.issue_key == key).one()
            issue.assignee_account_id = acct
            issue.assignee_name = name
        db.commit()
    finally:
        db.close()

    r = client.post("/api/match", json={"board_id": 1, "text": "webhook retry backoff"})
    body = r.json()
    by_key = {c["issue_key"]: c for c in body["candidates"]}
    assert by_key["PAY-431"]["assignee_name"] == "Me Myself"
    assert by_key["PAY-431"]["is_mine"] is True
    if "PAY-99" in by_key:
        assert by_key["PAY-99"]["assignee_name"] == "Colleague Carol"
        assert by_key["PAY-99"]["is_mine"] is False


def test_git_context_no_repos_configured(client):
    # No GIT_REPO_PATHS set in this test env -> not detected, no error.
    r = client.get("/api/git/context")
    assert r.status_code == 200
    assert r.json()["detected"] is False


def test_git_context_reads_a_real_repo(client, monkeypatch):
    """Create a throwaway git repo on a feature branch and confirm detection."""
    repo = Path(_TMP) / "sample-repo"
    repo.mkdir(exist_ok=True)

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Tester")
    (repo / "readme.txt").write_text("hello")
    git("add", "-A")
    git("commit", "-m", "Add webhook retry backoff handling")
    git("checkout", "-b", "feature/PAY-431-webhook-retry")

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "git_repo_paths", [str(repo)])

    r = client.get("/api/git/context")
    body = r.json()
    assert body["detected"] is True
    assert body["branch"] == "feature/PAY-431-webhook-retry"
    assert body["issue_key"] == "PAY-431"
    assert "webhook retry" in body["suggested_text"]
    assert body["commits"], "expected at least one commit subject"
