"""Shared test fixtures. No test may hit a real Jira instance (section 14)."""

import pytest

from app.jira.client import JiraClient

BASE_URL = "https://example.atlassian.net"
EMAIL = "me@example.com"
TOKEN = "test-token-123"


@pytest.fixture
def jira_client():
    client = JiraClient(BASE_URL, EMAIL, TOKEN, timeout=5.0)
    yield client
    client.close()
