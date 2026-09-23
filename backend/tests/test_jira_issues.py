"""Tests for issue fetching, cursor search, and normalisation."""

import httpx
import respx

from app.jira.issues import (
    enhanced_search,
    fetch_board_issues,
    normalize_issue,
)
from tests.conftest import BASE_URL


def _raw_issue(key="PAY-431", desc=None, sprint=None, parent=None):
    fields = {
        "summary": "Fix webhook retry backoff",
        "description": desc,
        "issuetype": {"name": "Story"},
        "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
        "assignee": {"accountId": "acc-1", "displayName": "Ada Lovelace"},
        "updated": "2026-09-07T09:30:00.000+0530",
        "project": {"key": "PAY"},
    }
    if sprint is not None:
        fields["sprint"] = sprint
    if parent is not None:
        fields["parent"] = {"key": parent}
    return {"id": "10001", "key": key, "fields": fields}


@respx.mock
def test_fetch_board_issues_paginates_with_startat(jira_client):
    route = respx.get(f"{BASE_URL}/rest/agile/1.0/board/5/issue")
    route.side_effect = [
        httpx.Response(200, json={"total": 3, "issues": [_raw_issue("PAY-1"), _raw_issue("PAY-2")]}),
        httpx.Response(200, json={"total": 3, "issues": [_raw_issue("PAY-3")]}),
    ]
    issues = fetch_board_issues(jira_client, 5, page_size=2)
    assert [i["key"] for i in issues] == ["PAY-1", "PAY-2", "PAY-3"]
    assert route.call_count == 2


@respx.mock
def test_fetch_board_issues_stops_on_short_page(jira_client):
    respx.get(f"{BASE_URL}/rest/agile/1.0/board/5/issue").mock(
        return_value=httpx.Response(200, json={"issues": [_raw_issue("PAY-1")]})
    )
    issues = fetch_board_issues(jira_client, 5, page_size=50)
    assert len(issues) == 1


@respx.mock
def test_enhanced_search_follows_next_page_token(jira_client):
    route = respx.get(f"{BASE_URL}/rest/api/3/search/jql")
    route.side_effect = [
        httpx.Response(200, json={"issues": [_raw_issue("PAY-1")], "nextPageToken": "tok2", "isLast": False}),
        httpx.Response(200, json={"issues": [_raw_issue("PAY-2")], "isLast": True}),
    ]
    issues = enhanced_search(jira_client, "project = PAY", page_size=1)
    assert [i["key"] for i in issues] == ["PAY-1", "PAY-2"]
    # Second call must carry the nextPageToken.
    assert "nextPageToken=tok2" in str(route.calls[1].request.url)


def test_normalize_issue_description_none():
    out = normalize_issue(_raw_issue(desc=None))
    assert out["description_text"] == ""
    assert out["issue_key"] == "PAY-431"
    assert out["issue_type"] == "Story"
    assert out["status"] == "In Progress"
    assert out["status_category"] == "In Progress"
    assert out["assignee_account_id"] == "acc-1"
    assert out["assignee_name"] == "Ada Lovelace"
    assert out["project_key"] == "PAY"
    assert out["updated_at"] is not None


def test_normalize_issue_description_plain_string():
    out = normalize_issue(_raw_issue(desc="a legacy plain string description"))
    assert out["description_text"] == "a legacy plain string description"


def test_normalize_issue_description_adf_dict():
    adf = {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "retry backoff logic"}]}],
    }
    out = normalize_issue(_raw_issue(desc=adf))
    assert "retry backoff logic" in out["description_text"]


def test_normalize_issue_sprint_dict_and_list():
    assert normalize_issue(_raw_issue(sprint={"name": "Sprint 12"}))["sprint_name"] == "Sprint 12"
    assert normalize_issue(_raw_issue(sprint=[{"name": "S1"}, {"name": "S2"}]))["sprint_name"] == "S2"
    assert normalize_issue(_raw_issue(sprint=None))["sprint_name"] is None


def test_normalize_issue_parent_key_for_subtask():
    out = normalize_issue(_raw_issue(parent="PAY-100"))
    assert out["parent_key"] == "PAY-100"


def test_normalize_issue_project_key_derived_from_key_when_missing():
    raw = _raw_issue("GTW-9")
    del raw["fields"]["project"]
    out = normalize_issue(raw)
    assert out["project_key"] == "GTW"


def test_normalize_issue_carries_board_id():
    out = normalize_issue(_raw_issue(), board_id=42)
    assert out["board_id"] == 42
