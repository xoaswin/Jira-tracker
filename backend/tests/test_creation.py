"""Phase 4 unit tests: type decision, draft text, createmeta parsing, payloads.

Pure-logic tests with no Jira calls. The API-level create/draft flow (with respx
mocking) lives in test_api_creation.py.
"""

from app.jira.create_issue import build_create_payload
from app.jira.createmeta import AUTO_FILLED_FIELDS, IssueTypeMeta
from app.services.drafting import (
    DUPLICATE_THRESHOLD,
    _draft_text,
    decide_issue_type,
)


# --- story vs subtask decision rule (section 5.5) ---

def test_explicit_subtask_of_in_text_wins():
    it, parent = decide_issue_type("subtask of PAY-431: fix the retry timing")
    assert it == "Sub-task"
    assert parent == "PAY-431"


def test_subtask_of_various_spellings():
    assert decide_issue_type("sub-task of GTW-9 do the thing")[1] == "GTW-9"
    assert decide_issue_type("Subtask Of ABC-1 stuff")[1] == "ABC-1"


def test_type_hint_subtask_with_parent():
    it, parent = decide_issue_type("do the thing", type_hint="subtask", parent_key="PAY-10")
    assert it == "Sub-task"
    assert parent == "PAY-10"


def test_type_hint_subtask_without_parent_falls_back_to_story():
    # A subtask needs a parent; without one we do not silently guess.
    it, parent = decide_issue_type("do the thing", type_hint="subtask")
    assert it == "Story"
    assert parent is None


def test_default_is_story():
    it, parent = decide_issue_type("improve the dashboard loading time")
    assert it == "Story"
    assert parent is None


# --- draft text (deterministic; no em dashes, section 18) ---

def test_draft_text_summary_and_description():
    summary, description = _draft_text("fixing the retry logic on the payment webhook")
    assert summary == "Fixing the retry logic on the payment webhook"
    assert "payment webhook" in description
    assert "—" not in summary and "—" not in description  # no em dash


def test_draft_text_has_structured_sections_and_criteria_checklist():
    # The offline fallback must produce a real skeleton, not a placeholder line.
    _, description = _draft_text("migrate 16 VMs in batch 2 and run cutover")
    assert "h3. Context" in description
    assert "h3. Scope" in description
    assert "h3. Acceptance Criteria" in description
    assert "* [ ]" in description  # a checklist the user fills in
    assert "migrate 16 VMs" in description.lower() or "16 vms" in description.lower()


def test_draft_text_empty():
    summary, description = _draft_text("")
    assert summary == "New work item"
    # Even with no input, the structure is present for the user to fill in.
    assert "h3. Acceptance Criteria" in description
    assert "* [ ]" in description


def test_draft_text_first_sentence_only_for_summary():
    summary, _ = _draft_text("Fix the bug. Then also refactor everything else massively.")
    assert summary == "Fix the bug."


# --- create payload (section 5.5) ---

def test_build_create_payload_story():
    payload = build_create_payload(
        project_key="PAY",
        issue_type_name="Story",
        summary="Do a thing",
        description="details here",
    )
    fields = payload["fields"]
    assert fields["project"] == {"key": "PAY"}
    assert fields["issuetype"] == {"name": "Story"}
    assert fields["summary"] == "Do a thing"
    assert fields["description"]["type"] == "doc"  # ADF
    assert "parent" not in fields


def test_build_create_payload_subtask_has_parent():
    payload = build_create_payload(
        project_key="PAY",
        issue_type_name="Sub-task",
        summary="child",
        description="d",
        parent_key="PAY-431",
    )
    assert payload["fields"]["parent"] == {"key": "PAY-431"}


def test_build_create_payload_merges_extra_fields():
    payload = build_create_payload(
        project_key="PAY",
        issue_type_name="Story",
        summary="s",
        description="d",
        extra_fields={"customfield_10001": {"value": "Team A"}},
    )
    assert payload["fields"]["customfield_10001"] == {"value": "Team A"}


# --- misc invariants ---

def test_auto_filled_fields_cover_the_basics():
    for f in ("summary", "description", "project", "issuetype", "parent"):
        assert f in AUTO_FILLED_FIELDS


def test_duplicate_threshold_is_point_eight():
    assert DUPLICATE_THRESHOLD == 0.8


def test_issue_type_meta_dataclass():
    m = IssueTypeMeta(id="10001", name="Story", subtask=False)
    assert m.id == "10001" and m.subtask is False
