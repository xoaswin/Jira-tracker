"""Issue-scope tests: which issues a board caches (any-assignee by default)."""

import inspect

from app.jira.issues import (
    DEFAULT_ISSUE_SCOPE,
    ISSUE_SCOPE_JQL,
    OPEN_ON_BOARD_JQL,
    fetch_board_issues,
)


def test_default_scope_is_open_on_board_any_assignee():
    assert DEFAULT_ISSUE_SCOPE == "open_on_board"
    jql = ISSUE_SCOPE_JQL[DEFAULT_ISSUE_SCOPE]
    assert "currentUser" not in jql  # not restricted to the current user
    assert "statusCategory != Done" in jql


def test_fetch_default_jql_is_open_on_board():
    default = inspect.signature(fetch_board_issues).parameters["jql"].default
    assert default == OPEN_ON_BOARD_JQL
    assert "currentUser" not in default


def test_all_named_scopes_present():
    for key in ("open_on_board", "assigned_to_me", "mine_all_status", "all_on_board"):
        assert key in ISSUE_SCOPE_JQL


def test_assigned_to_me_scope_still_available():
    assert "currentUser" in ISSUE_SCOPE_JQL["assigned_to_me"]
    assert "statusCategory != Done" in ISSUE_SCOPE_JQL["assigned_to_me"]
