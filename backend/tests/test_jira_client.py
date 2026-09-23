"""Tests for the Jira HTTP client: auth, errors, redaction, retry-after."""

import base64

import httpx
import pytest
import respx

from app.jira.client import JiraError, JiraClient, _redact
from tests.conftest import BASE_URL, EMAIL, TOKEN


@respx.mock
def test_myself_success_and_auth_header(jira_client):
    route = respx.get(f"{BASE_URL}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "abc123", "displayName": "Me"})
    )
    result = jira_client.myself()
    assert result["accountId"] == "abc123"

    # The Authorization header must be Basic base64(email:token).
    sent = route.calls.last.request.headers["authorization"]
    expected = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    assert sent == expected


@respx.mock
def test_non_2xx_raises_jira_error_with_body(jira_client):
    respx.post(f"{BASE_URL}/rest/api/3/issue/PAY-1/worklog").mock(
        return_value=httpx.Response(
            400, json={"errorMessages": [], "errors": {"timeSpentSeconds": "bad"}}
        )
    )
    with pytest.raises(JiraError) as exc:
        jira_client.post("/rest/api/3/issue/PAY-1/worklog", json_body={"x": 1})
    err = exc.value
    assert err.status_code == 400
    assert err.body["errors"]["timeSpentSeconds"] == "bad"
    assert err.is_permanent() is True


@respx.mock
def test_401_403_404_are_permanent(jira_client):
    for code in (401, 403, 404):
        respx.get(f"{BASE_URL}/rest/api/3/myself").mock(
            return_value=httpx.Response(code, json={"msg": "no"})
        )
        with pytest.raises(JiraError) as exc:
            jira_client.myself()
        assert exc.value.is_permanent() is True


@respx.mock
def test_429_is_not_permanent_and_parses_retry_after(jira_client):
    respx.get(f"{BASE_URL}/rest/api/3/myself").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"}, json={})
    )
    with pytest.raises(JiraError) as exc:
        jira_client.myself()
    assert exc.value.status_code == 429
    assert exc.value.is_permanent() is False
    assert exc.value.retry_after == 30.0


@respx.mock
def test_500_is_not_permanent(jira_client):
    respx.get(f"{BASE_URL}/rest/api/3/myself").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(JiraError) as exc:
        jira_client.myself()
    assert exc.value.is_permanent() is False
    assert exc.value.body == "boom"


@respx.mock
def test_timeout_raises_jira_error_with_no_status(jira_client):
    respx.get(f"{BASE_URL}/rest/api/3/myself").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    with pytest.raises(JiraError) as exc:
        jira_client.myself()
    assert exc.value.status_code is None
    assert exc.value.is_permanent() is False


@respx.mock
def test_204_returns_none(jira_client):
    respx.post(f"{BASE_URL}/rest/api/3/thing").mock(
        return_value=httpx.Response(204)
    )
    assert jira_client.post("/rest/api/3/thing", json_body={}) is None


def test_redact_masks_authorization_case_insensitive():
    masked = _redact({"Authorization": "Basic secret", "Accept": "application/json"})
    assert masked["Authorization"] == "Basic ***REDACTED***"
    assert masked["Accept"] == "application/json"
    masked2 = _redact({"authorization": "Basic secret"})
    assert masked2["authorization"] == "Basic ***REDACTED***"


def test_error_to_dict_shape():
    err = JiraError("bad", status_code=400, body={"e": 1}, method="POST", url="/x")
    d = err.to_dict()
    assert d["status_code"] == 400 and d["body"] == {"e": 1} and d["method"] == "POST"
