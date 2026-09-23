"""Tests for ADF conversion helpers (section 14: ADF round trip + None/str/dict)."""

from app.jira.adf import adf_to_text, flatten_adf, rich_text_to_adf, text_to_adf


def test_text_to_adf_single_paragraph():
    doc = text_to_adf("hello world")
    assert doc["type"] == "doc"
    assert doc["version"] == 1
    assert doc["content"] == [
        {"type": "paragraph", "content": [{"type": "text", "text": "hello world"}]}
    ]


def test_text_to_adf_multiple_paragraphs_split_on_blank_lines():
    doc = text_to_adf("first para\n\nsecond para")
    texts = [c["content"][0]["text"] for c in doc["content"]]
    assert texts == ["first para", "second para"]


def test_text_to_adf_empty_input_is_structurally_valid():
    doc = text_to_adf("")
    assert doc == {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": []}],
    }


def test_text_to_adf_whitespace_only_is_empty_paragraph():
    doc = text_to_adf("   \n\n   ")
    assert doc["content"] == [{"type": "paragraph", "content": []}]


def test_adf_to_text_handles_none():
    assert adf_to_text(None) == ""


def test_adf_to_text_handles_plain_string():
    # Some instances / v2 responses return a plain string for description.
    assert adf_to_text("just a string") == "just a string"


def test_adf_to_text_handles_nested_dict():
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "line one"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "line two"}]},
        ],
    }
    out = adf_to_text(doc)
    assert "line one" in out
    assert "line two" in out


def test_adf_to_text_handles_hard_break():
    node = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "a"},
            {"type": "hardBreak"},
            {"type": "text", "text": "b"},
        ],
    }
    assert "a\nb" in adf_to_text(node)


def test_round_trip_preserves_paragraphs():
    original = "first paragraph\n\nsecond paragraph\n\nthird paragraph"
    doc = text_to_adf(original)
    recovered = flatten_adf(doc)
    assert recovered == original


def test_round_trip_single_paragraph():
    original = "only one paragraph here"
    assert flatten_adf(text_to_adf(original)) == original


# --- rich_text_to_adf: structured issue descriptions ---

def _types(doc):
    return [node["type"] for node in doc["content"]]


def test_rich_heading_becomes_heading_node():
    doc = rich_text_to_adf("h3. Context\nSome background.")
    assert doc["content"][0]["type"] == "heading"
    assert doc["content"][0]["attrs"]["level"] == 3
    assert doc["content"][0]["content"][0]["text"] == "Context"
    assert doc["content"][1]["type"] == "paragraph"


def test_rich_checklist_becomes_tasklist_with_checkboxes():
    doc = rich_text_to_adf(
        "h3. Acceptance Criteria\n"
        "* [ ] All 16 VMs migrated\n"
        "* [x] Cutover signed off\n"
    )
    task_lists = [n for n in doc["content"] if n["type"] == "taskList"]
    assert len(task_lists) == 1
    items = task_lists[0]["content"]
    assert len(items) == 2
    assert all(i["type"] == "taskItem" for i in items)
    assert items[0]["attrs"]["state"] == "TODO"
    assert items[1]["attrs"]["state"] == "DONE"
    assert items[0]["content"][0]["text"] == "All 16 VMs migrated"
    # localIds must be unique (Jira rejects duplicates).
    ids = [i["attrs"]["localId"] for i in items]
    assert len(set(ids)) == len(ids)


def test_rich_plain_bullets_become_bulletlist():
    doc = rich_text_to_adf("h3. Scope\n* Do A\n* Do B")
    bl = [n for n in doc["content"] if n["type"] == "bulletList"]
    assert len(bl) == 1
    assert len(bl[0]["content"]) == 2
    assert bl[0]["content"][0]["type"] == "listItem"


def test_rich_tasks_and_bullets_do_not_merge():
    # A task line ("* [ ]") must not be swallowed into a bulletList.
    doc = rich_text_to_adf("* a normal bullet\n* [ ] a task")
    types = _types(doc)
    assert "bulletList" in types and "taskList" in types


def test_rich_plain_prose_falls_back_to_paragraphs():
    doc = rich_text_to_adf("just a sentence.\n\nanother one.")
    assert _types(doc) == ["paragraph", "paragraph"]


def test_rich_empty_is_valid_doc():
    doc = rich_text_to_adf("")
    assert doc["type"] == "doc" and doc["version"] == 1
    assert doc["content"] == [{"type": "paragraph", "content": []}]


def test_rich_full_draft_shape():
    draft = (
        "h3. Context\n"
        "Batch 2 of the migration is due.\n\n"
        "h3. Scope\n"
        "* Migrate 16 VMs\n"
        "* Run cutover\n\n"
        "h3. Acceptance Criteria\n"
        "* [ ] All VMs reachable post-migration\n"
        "* [ ] Zero data loss verified\n"
    )
    doc = rich_text_to_adf(draft)
    types = _types(doc)
    assert types.count("heading") == 3
    assert "bulletList" in types
    assert "taskList" in types
