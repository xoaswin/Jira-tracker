"""Tests for the git worklog-draft primitives against a throwaway repo."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from app.integrations.git import (
    commits_since,
    diffstat_since,
    find_repo_for_issue,
)


@pytest.fixture
def repo():
    d = Path(tempfile.mkdtemp(prefix="jt-gitwl-"))

    def git(*args):
        subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True)

    subprocess.run(["git", "init", str(d)], check=True, capture_output=True)
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Tester")
    # A baseline commit well in the past-ish (all commits share ~now, but the
    # cutoff test uses "now" boundaries loosely; we assert relative behaviour).
    (d / "a.txt").write_text("one")
    git("add", "-A")
    git("commit", "-m", "PAY-9 initial baseline")
    git("checkout", "-b", "feature/PAY-9-webhook-retry")
    yield d, git


def test_commits_and_diffstat_since_epoch(repo):
    d, git = repo
    (d / "b.txt").write_text("two")
    git("add", "-A")
    git("commit", "-m", "Add retry backoff with jitter")

    # Since the epoch, we see every commit and a diffstat with changed files.
    commits = commits_since(str(d), "1970-01-01T00:00:00+0000")
    assert "Add retry backoff with jitter" in commits
    stat = diffstat_since(str(d), "1970-01-01T00:00:00+0000")
    assert "b.txt" in stat or "a.txt" in stat


def test_commits_since_future_is_empty(repo):
    d, _ = repo
    # Nothing committed after a far-future cutoff.
    assert commits_since(str(d), "2999-01-01T00:00:00+0000") == []


def test_find_repo_for_issue_matches_branch_key(repo):
    d, _ = repo
    assert find_repo_for_issue([str(d)], "PAY-9") == str(d)
    assert find_repo_for_issue([str(d)], "PAY-999") is None


def test_primitives_never_raise_on_bad_path():
    assert commits_since("/no/such/repo", "1970-01-01T00:00:00+0000") == []
    assert diffstat_since("/no/such/repo", "1970-01-01T00:00:00+0000") == ""
    assert find_repo_for_issue(["/no/such/repo"], "PAY-1") is None
