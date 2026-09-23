"""Matching service: turn cached issues into ranked candidates (section 6).

Bridges the ORM (``Issue`` rows) and the pure ranker. Also owns embedding
maintenance: computing an issue's embedding when first cached or when its text
changes, and rebuilding all embeddings if the configured model changes.

All embedding work is best-effort. If the model is unavailable the ranker falls
back to BM25 + recency and the app stays fully usable (section 6).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching.embeddings import (
    embed_texts,
    embeddings_available,
    serialize,
)
from app.matching.ranker import Candidate, MatchResult, rank
from app.models import AppSettings, Issue

logger = logging.getLogger("jira_tracker.matching")

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def _embedding_model_name(db: Session) -> str:
    settings = db.get(AppSettings, 1)
    if settings and settings.embedding_model:
        return settings.embedding_model
    return DEFAULT_EMBEDDING_MODEL


def _issue_to_candidate(issue: Issue) -> Candidate:
    return Candidate(
        issue_key=issue.issue_key,
        summary=issue.summary or "",
        description_text=issue.description_text or "",
        issue_type=issue.issue_type,
        status=issue.status,
        status_category=issue.status_category,
        sprint_name=issue.sprint_name,
        updated_at=issue.updated_at,
        assignee_name=issue.assignee_name,
        assignee_account_id=issue.assignee_account_id,
        embedding=issue.embedding,
        embedding_model=issue.embedding_model,
    )


def match_board_issues(
    db: Session,
    board_id: int,
    text: str,
    *,
    branch_key: str | None = None,
) -> MatchResult:
    """Rank a single board's cached issues against ``text``.

    Thin wrapper over :func:`match_boards_issues` for the common single-board
    case; kept for backward compatibility.
    """
    return match_boards_issues(db, [board_id], text, branch_key=branch_key)


def match_boards_issues(
    db: Session,
    board_ids: list[int],
    text: str,
    *,
    branch_key: str | None = None,
) -> MatchResult:
    """Rank the cached issues across one or more boards against ``text``.

    Pinned-board search (section 6 extended): the candidate set is the union of
    the given boards' cached issues, deduplicated by issue key (a board can span
    projects and the same issue can appear on more than one board). Ensures
    embeddings are current first (best-effort), then runs the deterministic
    ranker over the combined set.
    """
    model_name = _embedding_model_name(db)
    if not board_ids:
        return rank(text, [], embedding_model=model_name, branch_key=branch_key)

    issues = list(
        db.execute(select(Issue).where(Issue.board_id.in_(board_ids))).scalars().all()
    )
    ensure_embeddings(db, issues, model_name)

    # Deduplicate by issue key so an issue on multiple boards is ranked once.
    seen: set[str] = set()
    candidates = []
    for issue in issues:
        if issue.issue_key in seen:
            continue
        seen.add(issue.issue_key)
        candidates.append(_issue_to_candidate(issue))

    return rank(
        text,
        candidates,
        embedding_model=model_name,
        branch_key=branch_key,
        enable_embeddings=True,
    )


def _issue_embedding_text(issue: Issue) -> str:
    return f"{issue.summary or ''} {issue.description_text or ''}".strip()


def ensure_embeddings(db: Session, issues: list[Issue], model_name: str) -> int:
    """Compute embeddings for issues that lack one or whose model changed.

    Returns the number of embeddings (re)computed. No-op and returns 0 when the
    embedding model is unavailable, so callers never need to guard.
    """
    if not embeddings_available(model_name):
        return 0

    stale = [
        issue
        for issue in issues
        if issue.embedding is None or issue.embedding_model != model_name
    ]
    if not stale:
        return 0

    texts = [_issue_embedding_text(issue) for issue in stale]
    vectors = embed_texts(texts, model_name)
    if vectors is None:  # model became unavailable between the check and here
        return 0

    for issue, vec in zip(stale, vectors):
        issue.embedding = serialize(vec)
        issue.embedding_model = model_name
    db.commit()
    logger.info("Computed %d embeddings with model %s", len(stale), model_name)
    return len(stale)


def rebuild_all_embeddings(db: Session) -> int:
    """Recompute embeddings for every cached issue with the configured model.

    Called in the background on startup when the model name changed (section 6).
    """
    model_name = _embedding_model_name(db)
    if not embeddings_available(model_name):
        return 0
    issues = list(db.execute(select(Issue)).scalars().all())
    # Force recompute by clearing the stored model tag mismatch check.
    for issue in issues:
        if issue.embedding_model != model_name:
            issue.embedding = None
    return ensure_embeddings(db, issues, model_name)
