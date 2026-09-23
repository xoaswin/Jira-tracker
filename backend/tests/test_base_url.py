"""Regression tests for base-URL normalisation (a pasted board URL must not 500).

A user pasting a full board URL like
``https://acme.atlassian.net/jira/software/c/projects/PAY/boards/534`` used to
make the client call ``.../boards/534/rest/api/3/myself``, which Jira answered
with its SPA HTML at 200; the auth route then crashed calling ``.get`` on a
string. The client now reduces any pasted URL to the site root.
"""

from app.jira.client import JiraClient, normalize_base_url


def test_normalize_strips_board_path():
    assert (
        normalize_base_url(
            "https://acme.atlassian.net/jira/software/c/projects/PAY/boards/534"
        )
        == "https://acme.atlassian.net"
    )


def test_normalize_keeps_bare_root():
    assert normalize_base_url("https://acme.atlassian.net") == "https://acme.atlassian.net"
    assert normalize_base_url("https://acme.atlassian.net/") == "https://acme.atlassian.net"


def test_normalize_adds_https_scheme():
    assert normalize_base_url("acme.atlassian.net") == "https://acme.atlassian.net"
    assert normalize_base_url("acme.atlassian.net/boards/1") == "https://acme.atlassian.net"


def test_normalize_strips_query_and_fragment():
    assert (
        normalize_base_url("https://acme.atlassian.net/x?y=1#z")
        == "https://acme.atlassian.net"
    )


def test_normalize_trims_whitespace_and_empty():
    assert normalize_base_url("  https://acme.atlassian.net/foo  ") == "https://acme.atlassian.net"
    assert normalize_base_url("") == ""


def test_client_uses_normalized_base_url():
    c = JiraClient(
        "https://acme.atlassian.net/jira/software/c/projects/PAY/boards/534",
        "me@acme.com",
        "tok",
    )
    try:
        assert c.base_url == "https://acme.atlassian.net"
    finally:
        c.close()
