"""Tests for active-sprint lookup and adding an issue to a sprint."""

import json

import httpx
import respx

from app.jira.client import JiraClient
from app.jira.sprints import add_issue_to_sprint, get_active_sprint_id

BASE = "https://acme.atlassian.net"


def _client():
    return JiraClient(BASE, "me@acme.com", "tok", timeout=5.0)


@respx.mock
def test_get_active_sprint_returns_id():
    c = _client()
    respx.get(f"{BASE}/rest/agile/1.0/board/5/sprint").mock(
        return_value=httpx.Response(200, json={"values": [{"id": 42, "name": "Sprint 7"}]})
    )
    assert get_active_sprint_id(c, 5) == 42
    c.close()


@respx.mock
def test_get_active_sprint_none_when_empty():
    c = _client()
    respx.get(f"{BASE}/rest/agile/1.0/board/5/sprint").mock(
        return_value=httpx.Response(200, json={"values": []})
    )
    assert get_active_sprint_id(c, 5) is None
    c.close()


@respx.mock
def test_get_active_sprint_none_on_kanban_400():
    c = _client()
    # Kanban boards 400 on the sprint endpoint; we must degrade to None.
    respx.get(f"{BASE}/rest/agile/1.0/board/9/sprint").mock(
        return_value=httpx.Response(400, json={"errorMessages": ["does not support sprints"]})
    )
    assert get_active_sprint_id(c, 9) is None
    c.close()


@respx.mock
def test_add_issue_to_sprint_posts_issue():
    c = _client()
    post = respx.post(f"{BASE}/rest/agile/1.0/sprint/42/issue").mock(
        return_value=httpx.Response(204)
    )
    add_issue_to_sprint(c, 42, "PAY-100")
    sent = json.loads(post.calls.last.request.read().decode())
    assert sent == {"issues": ["PAY-100"]}
    c.close()
