"""Config parsing regression tests.

GIT_REPO_PATHS is a comma-separated env var (section 16). pydantic-settings v2
tries to json.loads() list-typed env vars before field validators run, which
crashed startup on the documented format until ``NoDecode`` was added. Guard it.
"""

from app.config import Settings


def test_git_repo_paths_comma_separated(monkeypatch):
    monkeypatch.setenv("GIT_REPO_PATHS", "/a/one,/b/two , /c/three")
    s = Settings()
    assert s.git_repo_paths == ["/a/one", "/b/two", "/c/three"]


def test_git_repo_paths_single(monkeypatch):
    monkeypatch.setenv("GIT_REPO_PATHS", "/only/one")
    s = Settings()
    assert s.git_repo_paths == ["/only/one"]


def test_git_repo_paths_unset(monkeypatch):
    monkeypatch.delenv("GIT_REPO_PATHS", raising=False)
    s = Settings()
    assert s.git_repo_paths == []
