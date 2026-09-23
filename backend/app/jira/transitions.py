"""Issue transitions (section 5.6).

Transition ids are per workflow, not global, so we fetch the available
transitions for the specific issue and match by name case-insensitively. If no
transition matching the target name exists, we skip silently rather than
erroring (section 5.6).
"""

from __future__ import annotations

import logging

from app.jira.client import JiraClient, JiraError

logger = logging.getLogger("jira_tracker.transitions")


def get_transitions(client: JiraClient, issue_key: str) -> list[dict]:
    """GET the available transitions for an issue."""
    result = client.get(f"/rest/api/3/issue/{issue_key}/transitions")
    return result.get("transitions", []) if isinstance(result, dict) else []


def find_transition_id(client: JiraClient, issue_key: str, target_name: str) -> str | None:
    """Return the transition id whose name matches ``target_name`` (case-insensitive)."""
    target = target_name.strip().lower()
    for t in get_transitions(client, issue_key):
        if (t.get("name") or "").strip().lower() == target:
            return str(t.get("id"))
    return None


def transition_issue(client: JiraClient, issue_key: str, target_name: str) -> bool:
    """Transition an issue to a named status, or skip silently if unavailable.

    Returns True if a transition was performed, False if no matching transition
    exists (section 5.6: skip silently rather than erroring).
    """
    transition_id = find_transition_id(client, issue_key, target_name)
    if transition_id is None:
        logger.info(
            "no transition named %r on %s; skipping silently", target_name, issue_key
        )
        return False
    client.post(
        f"/rest/api/3/issue/{issue_key}/transitions",
        json_body={"transition": {"id": transition_id}},
    )
    return True


# --- auto-walk: apply intermediate transitions to reach a target status ---

# Jira status category keys, ordered To Do -> In Progress -> Done.
_CATEGORY_ORDER = {"new": 0, "undefined": 0, "indeterminate": 1, "done": 2}


def get_current_status(client: JiraClient, issue_key: str) -> dict:
    """Return {name, category_key} for the issue's current status."""
    data = client.get(f"/rest/api/3/issue/{issue_key}", params={"fields": "status"})
    status = ((data.get("fields") or {}).get("status")) or {}
    cat = (status.get("statusCategory") or {}).get("key")
    return {"name": status.get("name"), "category_key": cat}


def _category_rank(key: str | None) -> int:
    return _CATEGORY_ORDER.get((key or "").lower(), 0)


def _to_name(t: dict) -> str:
    return ((t.get("to") or {}).get("name") or "").strip().lower()


def _to_rank(t: dict) -> int:
    return _category_rank(((t.get("to") or {}).get("statusCategory") or {}).get("key"))


def walk_to_status(
    client: JiraClient, issue_key: str, target_name: str, *, max_steps: int = 8
) -> list[str]:
    """Apply transitions in sequence until the issue reaches ``target_name``.

    Jira only exposes transitions available from the *current* status, so we
    walk one step at a time, refetching after each:

      1. If already at the target status (by name), stop.
      2. If a transition reaches the target directly, take it.
      3. Otherwise advance toward the target's category: among transitions whose
         destination category is not past the target and whose destination we
         have not already visited, pick the one that advances the category the
         most (ties allow same-category progress, e.g. Draft -> To Do, since
         both are the "new" category). Apply, refetch, repeat.

    Visited-tracking prevents loops; ``max_steps`` is a hard backstop. Never
    overshoots past the target's category. Returns the transition names applied.
    """
    target = target_name.strip().lower()
    applied: list[str] = []
    visited: set[str] = set()

    for _ in range(max_steps):
        current = get_current_status(client, issue_key)
        current_name = (current["name"] or "").strip().lower()
        if current_name == target:
            return applied
        visited.add(current_name)

        transitions = get_transitions(client, issue_key)
        if not transitions:
            break

        # Target category: from any transition that reaches the named target,
        # else default to Done (the common "mark done" case).
        target_rank = 2
        for t in transitions:
            if _to_name(t) == target:
                target_rank = _to_rank(t)
                break

        # 1. Direct transition to the named target.
        direct = next((t for t in transitions if _to_name(t) == target), None)
        if direct:
            _apply(client, issue_key, direct)
            applied.append(direct.get("name") or "")
            continue

        # 2. Advance without overshooting the target category, avoiding statuses
        #    we have already been to (prevents cycles within a category).
        candidates = [
            t for t in transitions if _to_rank(t) <= target_rank and _to_name(t) not in visited
        ]
        if not candidates:
            break
        step = max(candidates, key=_to_rank)
        _apply(client, issue_key, step)
        applied.append(step.get("name") or "")

    return applied


def _apply(client: JiraClient, issue_key: str, transition: dict) -> None:
    client.post(
        f"/rest/api/3/issue/{issue_key}/transitions",
        json_body={"transition": {"id": str(transition.get("id"))}},
    )
