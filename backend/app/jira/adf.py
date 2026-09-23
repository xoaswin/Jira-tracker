"""Atlassian Document Format (ADF) helpers.

Jira Cloud REST API v3 does not accept plain strings for ``description`` or
comment ``body``. It expects Atlassian Document Format, a JSON tree. These
helpers are the only place in the app that needs to think about ADF.
"""

from __future__ import annotations

import re
from typing import Any


def text_to_adf(text: str) -> dict:
    """Convert plain text (with blank-line paragraph breaks) to minimal valid ADF.

    Paragraphs are split on blank lines. An empty or whitespace-only input still
    produces a structurally valid document with a single empty paragraph, which
    Jira accepts.
    """
    paragraphs = [p for p in (text or "").split("\n\n") if p.strip()]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": p.strip()}],
            }
            for p in paragraphs
        ]
        or [{"type": "paragraph", "content": []}],
    }


# --- Rich markdown-ish -> ADF (for AI/structured issue descriptions) ---
#
# The issue drafter emits a lightweight markup: "h3. Title" headings, "* " bullet
# items, and "* [ ] " / "* [x] " task-list items. Rendering these as real ADF
# nodes (heading, bulletList, taskList) means the acceptance criteria appear as
# genuine Jira checkboxes and headings rather than literal "* [ ]" text.

_HEADING_RE = re.compile(r"^h([1-6])\.\s+(.*)$")
_TASK_RE = re.compile(r"^[*\-]\s*\[( |x|X)\]\s+(.*)$")
_BULLET_RE = re.compile(r"^[*\-]\s+(.*)$")


def _text_node(s: str) -> dict:
    return {"type": "text", "text": s}


def _paragraph(s: str) -> dict:
    return {"type": "paragraph", "content": [_text_node(s)] if s else []}


def rich_text_to_adf(text: str) -> dict:
    """Convert the drafter's markup to structured ADF.

    Supported per line:
      * ``h1.``..``h6.``   -> heading of that level
      * ``* [ ] item``     -> taskList item (unchecked); ``[x]`` -> checked
      * ``* item``         -> bulletList item
      * blank line         -> separates blocks
      * anything else      -> paragraph

    Consecutive bullets group into one bulletList; consecutive tasks into one
    taskList. Falls back to :func:`text_to_adf` behaviour for plain prose.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    content: list[dict] = []
    bullet_buf: list[str] = []
    task_buf: list[str] = []
    task_counter = [0]

    def flush_bullets() -> None:
        if not bullet_buf:
            return
        content.append(
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [_paragraph(item)],
                    }
                    for item in bullet_buf
                ],
            }
        )
        bullet_buf.clear()

    def flush_tasks() -> None:
        if not task_buf:
            return
        items = []
        for state, label in task_buf:
            task_counter[0] += 1
            items.append(
                {
                    "type": "taskItem",
                    "attrs": {
                        "localId": f"task-{task_counter[0]}",
                        "state": "DONE" if state else "TODO",
                    },
                    "content": [_text_node(label)] if label else [],
                }
            )
        content.append(
            {
                "type": "taskList",
                "attrs": {"localId": f"tasklist-{task_counter[0]}"},
                "content": items,
            }
        )
        task_buf.clear()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_bullets()
            flush_tasks()
            continue

        heading = _HEADING_RE.match(stripped)
        task = _TASK_RE.match(stripped)
        bullet = _BULLET_RE.match(stripped)

        if task:  # check task BEFORE bullet, since "* [ ]" also matches bullet
            flush_bullets()
            checked = task.group(1).lower() == "x"
            task_buf.append((checked, task.group(2).strip()))
        elif bullet:
            flush_tasks()
            bullet_buf.append(bullet.group(1).strip())
        elif heading:
            flush_bullets()
            flush_tasks()
            content.append(
                {
                    "type": "heading",
                    "attrs": {"level": int(heading.group(1))},
                    "content": [_text_node(heading.group(2).strip())],
                }
            )
        else:
            flush_bullets()
            flush_tasks()
            content.append(_paragraph(stripped))

    flush_bullets()
    flush_tasks()

    if not content:
        content = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": content}


def adf_to_text(node: Any) -> str:
    """Recursively flatten an ADF document (or fragment) to plain text.

    Robust to the three shapes Jira actually returns for a description or body:

    * ``None``            -> empty string
    * a plain ``str``     -> returned as-is (some instances / v2 responses)
    * an ADF ``dict``     -> recursively flattened

    Block-level nodes (paragraphs, headings, list items, ...) are separated by
    blank lines so that a later ``text_to_adf`` round trip preserves paragraph
    structure. Hard breaks become newlines.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node

    # Node types that introduce their own text content.
    if isinstance(node, dict):
        node_type = node.get("type")

        if node_type == "text":
            return node.get("text", "")

        if node_type == "hardBreak":
            return "\n"

        # Recurse into children and join them.
        children = node.get("content", []) or []
        inner = "".join(adf_to_text(child) for child in children)

        # Block-level containers get separated by a blank line.
        block_types = {
            "paragraph",
            "heading",
            "blockquote",
            "listItem",
            "codeBlock",
            "panel",
        }
        if node_type in block_types:
            return inner + "\n\n"
        return inner

    if isinstance(node, list):
        return "".join(adf_to_text(child) for child in node)

    return ""


def flatten_adf(node: Any) -> str:
    """Flatten ADF to a single trimmed plain-text string, collapsing blank runs.

    Convenience wrapper around :func:`adf_to_text` for search indexing, where we
    want clean text rather than preserved paragraph spacing.
    """
    raw = adf_to_text(node)
    # Collapse 3+ newlines to a paragraph break, then strip.
    lines = [line.strip() for line in raw.split("\n")]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if line:
            collapsed.append(line)
            blank = False
        elif not blank:
            collapsed.append("")
            blank = True
    return "\n".join(collapsed).strip()
