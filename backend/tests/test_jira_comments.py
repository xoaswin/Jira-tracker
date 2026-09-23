"""Tests for comment creation and reading."""

import json

import httpx
import respx

from app.jira.comments import add_comment, get_comments
from tests.conftest import BASE_URL


@respx.mock
def test_add_comment_body_is_adf(jira_client):
    route = respx.post(f"{BASE_URL}/rest/api/3/issue/PAY-431/comment").mock(
        return_value=httpx.Response(201, json={"id": "70001"})
    )
    result = add_comment(jira_client, "PAY-431", "Fixed the retry backoff")
    assert result["id"] == "70001"

    body = json.loads(route.calls.last.request.read().decode())
    assert body["body"]["type"] == "doc"
    assert body["body"]["content"][0]["content"][0]["text"] == "Fixed the retry backoff"


@respx.mock
def test_get_comments(jira_client):
    respx.get(f"{BASE_URL}/rest/api/3/issue/PAY-431/comment").mock(
        return_value=httpx.Response(200, json={"comments": [{"id": "1"}]})
    )
    comments = get_comments(jira_client, "PAY-431")
    assert comments[0]["id"] == "1"
