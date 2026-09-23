"""Issue drafting: decide type, draft text, and guard against duplicates.

This is the read-only half of creation (section 15 rule 1: never write to Jira
without an explicit confirmation click). It:

* applies the deterministic story-vs-subtask rule (section 5.5) BEFORE any AI,
* produces a draft summary + description (a plain-text draft for now; Phase 5
  swaps in the AI provider behind the same seam, section 8),
* discovers required custom fields via createmeta (section 5.5),
* runs the duplicate guard against all open project issues (section 7).

Nothing here writes to Jira.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.jira.client import JiraClient, JiraError
from app.jira.createmeta import RequiredField, find_issue_type, get_required_fields
from app.jira.issues import enhanced_search, normalize_issue
from app.matching.embeddings import embed_text, embeddings_available, serialize
from app.matching.similarity import duplicate_similarity
from app.models import Board
from app.services.matching import DEFAULT_EMBEDDING_MODEL, _embedding_model_name

logger = logging.getLogger("jira_tracker.drafting")

DUPLICATE_THRESHOLD = 0.8  # section 7: block above this similarity

# "subtask of X" or "sub-task of PAY-431" in the description (section 5.5).
_SUBTASK_OF_RE = re.compile(r"sub[-\s]?task\s+of\s+([A-Z][A-Z0-9]+-\d+)", re.IGNORECASE)


@dataclass
class DuplicateWarning:
    issue_key: str
    summary: str
    similarity: float


@dataclass
class IssueDraft:
    project_key: str
    issue_type: str  # "Story" | "Sub-task" | ...
    summary: str
    description: str
    parent_key: str | None = None
    required_fields: list[RequiredField] = field(default_factory=list)
    duplicate: DuplicateWarning | None = None


def decide_issue_type(
    text: str,
    *,
    type_hint: str | None = None,
    parent_key: str | None = None,
) -> tuple[str, str | None]:
    """Return (issue_type, parent_key) using the section 5.5 rule.

    Order of precedence:
    1. An explicit "subtask of X" in the text -> Sub-task under X.
    2. A caller type_hint of "subtask" plus a parent_key -> Sub-task.
    3. Otherwise -> Story.
    """
    explicit = _SUBTASK_OF_RE.search(text or "")
    if explicit:
        return "Sub-task", explicit.group(1).upper()

    if type_hint and type_hint.strip().lower() in {"subtask", "sub-task"} and parent_key:
        return "Sub-task", parent_key.upper()

    return "Story", None


def _draft_text(text: str) -> tuple[str, str]:
    """Deterministic draft summary + structured description from the raw text.

    This is the always-on fallback used when AI is disabled or unreachable
    (section 8). It cannot infer acceptance criteria from prose the way a model
    can, but it produces a proper structured skeleton (Context, Scope,
    Acceptance Criteria checklist, Out of Scope) seeded from the input so the
    confirmation dialog is a fill-in-the-blanks form, not a blank box. No em
    dashes (section 18).
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        summary = "New work item"
    else:
        first = re.split(r"(?<=[.!?])\s", cleaned, maxsplit=1)[0]
        summary = first[:120].strip()
        if summary and summary[0].islower():
            summary = summary[0].upper() + summary[1:]

    # Split the input into sentence-ish fragments to seed scope bullets.
    fragments = [f.strip() for f in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if f.strip()]
    scope_bullets = "\n".join(f"* {f}" for f in fragments) if fragments else "* (define the work)"

    context = cleaned if cleaned else "(describe the background and why this is needed)"
    description = (
        f"h3. Context\n{context}\n\n"
        f"h3. Scope\n{scope_bullets}\n\n"
        "h3. Acceptance Criteria\n"
        "* [ ] (add a specific, testable criterion)\n"
        "* [ ] (add another)\n\n"
        "h3. Out of Scope\n"
        "* (optional: what this ticket does not cover)"
    )
    return summary, description


def _draft_text_ai(db: Session, text: str) -> tuple[str, str, bool]:
    """AI-improved draft, falling back to :func:`_draft_text` on any failure.

    Returns ``(summary, description, used_ai)``. The model is prompted to return
    "summary\\n\\ndescription"; we split on the first blank line. If AI is
    disabled/unreachable, ``safe_generate`` returns ``used_ai=False`` and we use
    the deterministic draft (section 8: AI improves wording, never load bearing).
    """
    # Import here to avoid a heavy import at module load and to keep the AI layer
    # optional for the deterministic paths.
    from app.ai.factory import get_provider, safe_generate
    from app.ai.prompts import DRAFT_ISSUE_SYSTEM, draft_issue_user

    if not (text or "").strip():
        summary, description = _draft_text(text)
        return summary, description, False

    provider = get_provider(db)
    out, used_ai = safe_generate(
        provider, DRAFT_ISSUE_SYSTEM, draft_issue_user(text), max_tokens=1200, timeout=25.0
    )
    if not used_ai:
        summary, description = _draft_text(text)
        return summary, description, False

    # Parse "summary\n\ndescription". Guard against a model that returns only one.
    parts = out.split("\n\n", 1)
    summary = " ".join(parts[0].split()).strip()
    description = parts[1].strip() if len(parts) > 1 else out.strip()
    if not summary:
        summary, description = _draft_text(text)
        return summary, description, False
    return summary[:255], description, True


def duplicate_guard(
    db: Session,
    client: JiraClient,
    project_key: str,
    text: str,
) -> DuplicateWarning | None:
    """Search ALL open issues in the project and warn on a >=0.8 match (section 7).

    Runs against the project, not just the current board or the current user, so
    near-duplicates created by anyone are caught. Best-effort: a Jira search
    failure logs and returns None rather than blocking creation.

    Uses absolute pairwise similarity (``matching.similarity``), NOT the ranker's
    corpus-normalised score, because the guard asks an absolute question and must
    still fire in a project with only a handful of open issues.
    """
    jql = f'project = "{project_key}" AND statusCategory != Done ORDER BY updated DESC'
    try:
        raw = enhanced_search(client, jql, max_results=100)
    except JiraError as exc:
        logger.warning("duplicate guard search failed for %s: %s", project_key, exc)
        return None
    if not raw:
        return None

    model_name = _embedding_model_name(db) or DEFAULT_EMBEDDING_MODEL
    use_embeddings = embeddings_available(model_name)

    best: DuplicateWarning | None = None
    for r in raw:
        data = normalize_issue(r)
        # Embed the existing issue on the fly when embeddings are available; these
        # project-wide issues are not necessarily in our per-board cache.
        blob = None
        if use_embeddings:
            issue_vec = embed_text(
                f"{data['summary']} {data['description_text']}", model_name
            )
            blob = serialize(issue_vec)

        sim = duplicate_similarity(
            text,
            summary=data["summary"],
            description=data["description_text"],
            embedding_blob=blob,
            embedding_model=model_name,
        )
        if sim >= DUPLICATE_THRESHOLD and (best is None or sim > best.similarity):
            best = DuplicateWarning(
                issue_key=data["issue_key"],
                summary=data["summary"],
                similarity=round(sim, 3),
            )
    return best


def build_draft(
    db: Session,
    client: JiraClient,
    *,
    board_id: int,
    text: str,
    type_hint: str | None = None,
    parent_key: str | None = None,
    run_duplicate_guard: bool = True,
) -> IssueDraft:
    """Assemble a full draft: type, text, required fields, duplicate warning."""
    board = db.get(Board, board_id)
    if board is None:
        raise ValueError(f"Board {board_id} not found")
    if not board.project_key:
        raise ValueError(
            f"Board {board_id} has no resolved project key; refresh boards first."
        )
    project_key = board.project_key

    issue_type, resolved_parent = decide_issue_type(
        text, type_hint=type_hint, parent_key=parent_key
    )
    summary, description, _used_ai = _draft_text_ai(db, text)

    # Required custom fields for this project + issue type (section 5.5).
    required: list[RequiredField] = []
    it_meta = find_issue_type(client, project_key, issue_type)
    if it_meta is not None:
        required = get_required_fields(client, project_key, it_meta.id)

    duplicate = None
    if run_duplicate_guard:
        duplicate = duplicate_guard(db, client, project_key, text)

    return IssueDraft(
        project_key=project_key,
        issue_type=issue_type,
        summary=summary,
        description=description,
        parent_key=resolved_parent,
        required_fields=required,
        duplicate=duplicate,
    )
