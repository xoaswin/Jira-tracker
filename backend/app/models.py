"""SQLAlchemy ORM models for Phase 1: boards, issues, sessions, settings.

The outbox table arrives in Phase 2. Phase 1 records the result of the direct
synchronous push directly on the session row (``sync_state`` and the returned
Jira ids); Phase 2 moves that responsibility into the durable outbox.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BLOB,
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime


# Alias so column definitions read naturally while using the UTC-normalising type.
DateTime = UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Board(Base):
    __tablename__ = "boards"

    # Jira board id, not auto-generated.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str | None] = mapped_column(String, nullable=True)  # scrum | kanban
    project_key: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_favourite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jira_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    issue_key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    board_id: Mapped[int | None] = mapped_column(
        ForeignKey("boards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_key: Mapped[str | None] = mapped_column(String, nullable=True)
    issue_type: Mapped[str | None] = mapped_column(String, nullable=True)  # Story|Sub-task|Task|Bug
    parent_key: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    status_category: Mapped[str | None] = mapped_column(String, nullable=True)  # To Do|In Progress|Done
    assignee_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    assignee_name: Mapped[str | None] = mapped_column(String, nullable=True)
    sprint_name: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Phase 3 fields, nullable now.
    embedding: Mapped[bytes | None] = mapped_column(BLOB, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkSession(Base):
    """A local work session. Table name is ``sessions`` per the spec."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    board_id: Mapped[int | None] = mapped_column(
        ForeignKey("boards.id", ondelete="SET NULL"), nullable=True
    )
    issue_key: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # When state == "paused", the instant the current pause began; else NULL.
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adjusted_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String, default="active", nullable=False)
    # active | paused | completed | abandoned
    issue_origin: Mapped[str | None] = mapped_column(String, nullable=True)
    # matched | created | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # --- Phase 1 direct-push tracking (superseded by the outbox in Phase 2) ---
    worklog_jira_id: Mapped[str | None] = mapped_column(String, nullable=True)
    comment_jira_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sync_state: Mapped[str] = mapped_column(String, default="unsynced", nullable=False)
    # unsynced | synced | error
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Outbox(Base):
    """Durable queue of pending Jira writes (section 4, Phase 2)."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # worklog | comment | transition | create_issue
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String, default="pending", nullable=False, index=True)
    # pending | in_flight | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False, index=True
    )
    jira_result_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AppSettings(Base):
    """Single-row settings table (id is always 1)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    jira_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    jira_email: Mapped[str | None] = mapped_column(String, nullable=True)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)

    ai_provider: Mapped[str] = mapped_column(String, default="ollama", nullable=False)
    ollama_url: Mapped[str | None] = mapped_column(String, nullable=True)
    ollama_model: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)

    nudge_time: Mapped[str | None] = mapped_column(String, nullable=True)
    idle_threshold_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    default_transition: Mapped[str | None] = mapped_column(String, nullable=True)

    # Work window + accountability (local clock). Used by the daily-completeness
    # nudge and the hourly "what are you working on?" check-in. Times are "HH:MM"
    # in the user's local timezone. daily_target_hours is the expected logged
    # time per day (e.g. 7.5 for a 9h day with a 1h break); a nudge fires when
    # the day's tracked total falls short after work_end_time.
    work_start_time: Mapped[str | None] = mapped_column(String, nullable=True)
    work_end_time: Mapped[str | None] = mapped_column(String, nullable=True)
    daily_target_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # 0 disables the recurring check-in; otherwise minutes between prompts.
    checkin_interval_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # When true, finishing/logging a session best-effort stamps the ticket's
    # "actual start" (if not already set) and "actual end" date fields from the
    # session's start/end, so you never hand-edit them. Off by default.
    auto_actual_dates: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uses_tempo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Which issues to cache/search per board (see app.jira.issues.ISSUE_SCOPE_JQL).
    # Default "open_on_board": all not-Done issues, any assignee.
    issue_scope: Mapped[str] = mapped_column(
        String, default="open_on_board", nullable=False
    )

    # Set when the outbox worker hits a 401: the token is dead, so the worker
    # halts rather than burning retries against it (section 5.7). Cleared on
    # the next successful /api/auth/connect.
    needs_reauth: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
