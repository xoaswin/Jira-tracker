"""Tests for board listing, pagination, and normalisation."""

import httpx
import respx

from app.jira.boards import (
    get_board_configuration,
    list_boards,
    normalize_board,
    resolve_project_from_configuration,
)
from tests.conftest import BASE_URL


@respx.mock
def test_list_boards_follows_pagination(jira_client):
    route = respx.get(f"{BASE_URL}/rest/agile/1.0/board")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "isLast": False,
                "values": [{"id": 1, "name": "Payments"}, {"id": 2, "name": "Gateway"}],
            },
        ),
        httpx.Response(
            200,
            json={"isLast": True, "values": [{"id": 3, "name": "Ops"}]},
        ),
    ]
    boards = list_boards(jira_client, page_size=2)
    assert [b["id"] for b in boards] == [1, 2, 3]
    assert route.call_count == 2


@respx.mock
def test_get_board_configuration(jira_client):
    respx.get(f"{BASE_URL}/rest/agile/1.0/board/5/configuration").mock(
        return_value=httpx.Response(
            200,
            json={"id": 5, "name": "Payments", "location": {"projectKeyOrId": "PAY", "id": 10001}},
        )
    )
    config = get_board_configuration(jira_client, 5)
    resolved = resolve_project_from_configuration(config)
    assert resolved["project_key"] == "PAY"
    assert resolved["project_id"] == "10001"


def test_normalize_board_project_scoped():
    raw = {
        "id": 7,
        "name": "Payments board",
        "type": "scrum",
        "location": {"type": "project", "key": "PAY", "id": 10001, "name": "Payments"},
    }
    out = normalize_board(raw)
    assert out == {
        "id": 7,
        "name": "Payments board",
        "type": "scrum",
        "project_key": "PAY",
        "project_id": "10001",
    }


def test_normalize_board_projectkey_field_variant():
    raw = {"id": 8, "name": "b", "type": "kanban", "location": {"projectKey": "GTW", "projectId": 20002}}
    out = normalize_board(raw)
    assert out["project_key"] == "GTW"
    assert out["project_id"] == "20002"


def test_normalize_board_filter_board_without_project():
    raw = {"id": 9, "name": "Cross-project", "type": "kanban", "location": {"type": "user"}}
    out = normalize_board(raw)
    assert out["project_key"] is None
    assert out["project_id"] is None
