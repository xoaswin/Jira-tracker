"""AI text helpers for the narrow Phase 5 features (section 8).

Thin wrappers over the provider factory for the two user-facing "improve with
AI" actions and the optional daily summary. Each returns ``(text, used_ai)`` so
the UI can show an "AI unavailable" hint and offer an undo, and each degrades to
the raw input when AI is off or unreachable (never raises).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.factory import get_provider, safe_generate
from app.ai.prompts import (
    CLEANUP_COMMENT_SYSTEM,
    DAILY_SUMMARY_SYSTEM,
    WORKLOG_FROM_DIFF_SYSTEM,
    cleanup_comment_user,
    daily_summary_user,
    worklog_from_diff_user,
)
from app.config import get_settings
from app.integrations.git import commits_since, diffstat_since, find_repo_for_issue
from app.models import WorkSession
from app.services.duration import effective_duration_seconds


def cleanup_comment(db: Session, notes: str) -> tuple[str, bool]:
    """Turn rough session notes into a tidy worklog comment."""
    if not (notes or "").strip():
        return "", False
    provider = get_provider(db)
    return safe_generate(
        provider, CLEANUP_COMMENT_SYSTEM, cleanup_comment_user(notes), max_tokens=256
    )


@dataclass
class WorklogDraft:
    text: str
    used_ai: bool
    commit_count: int
    repo_path: str | None


def draft_worklog_from_git(
    db: Session, issue_key: str, since_iso: str
) -> WorklogDraft:
    """Draft a worklog comment from the git activity on ``issue_key``'s repo.

    Finds the configured repo whose current branch names ``issue_key``, collects
    the commit subjects and a diffstat since ``since_iso`` (the session start),
    and asks the AI to summarise them. Degrades cleanly:

    * no matching repo or no commits -> empty text, used_ai False, so the UI can
      say "no git activity found" rather than fabricate a comment;
    * AI off/unreachable -> the raw commit list is returned as the text
      (used_ai False), which is still a useful worklog on its own.
    """
    repo_paths = get_settings().git_repo_paths
    repo = find_repo_for_issue(repo_paths, issue_key)
    if repo is None:
        return WorklogDraft(text="", used_ai=False, commit_count=0, repo_path=None)

    commits = commits_since(repo, since_iso)
    diffstat = diffstat_since(repo, since_iso)
    if not commits and not diffstat:
        return WorklogDraft(text="", used_ai=False, commit_count=0, repo_path=repo)

    provider = get_provider(db)
    text, used_ai = safe_generate(
        provider,
        WORKLOG_FROM_DIFF_SYSTEM,
        worklog_from_diff_user(commits, diffstat),
        max_tokens=300,
        timeout=25.0,
    )
    # If AI is off/unreachable, safe_generate's NullProvider echoes the prompt;
    # prefer a clean human-readable fallback (the commit subjects) instead.
    if not used_ai:
        text = "\n".join(f"- {c}" for c in commits) if commits else ""
    return WorklogDraft(
        text=text, used_ai=used_ai, commit_count=len(commits), repo_path=repo
    )


def _fmt_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def daily_summary(db: Session, day: date | None = None) -> tuple[str, bool]:
    """Roll up a day's completed sessions into a short standup-style summary."""
    day = day or datetime.now(timezone.utc).date()
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(day, time.max, tzinfo=timezone.utc)
    stmt = (
        select(WorkSession)
        .where(
            WorkSession.state == "completed",
            WorkSession.started_at >= start,
            WorkSession.started_at <= end,
        )
        .order_by(WorkSession.started_at.asc())
    )
    sessions = list(db.execute(stmt).scalars().all())
    if not sessions:
        return "No completed sessions today.", False

    lines: list[str] = []
    for s in sessions:
        secs = effective_duration_seconds(
            s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
        )
        label = s.issue_key or "no ticket"
        desc = (s.notes or s.description or "").strip()
        lines.append(f"[{label}] {_fmt_hms(secs)}: {desc}")

    provider = get_provider(db)
    return safe_generate(
        provider, DAILY_SUMMARY_SYSTEM, daily_summary_user(lines), max_tokens=400
    )
