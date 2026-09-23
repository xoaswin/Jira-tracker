"""Enqueue durable Jira writes onto the outbox (section 4, Phase 2).

A session completion no longer calls Jira directly (that was Phase 1). It
enqueues one ``worklog`` item and, if there are notes, one ``comment`` item,
both due immediately (``next_attempt_at`` = now). The worker (``worker.py``)
is what actually talks to Jira, with retries and idempotency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Outbox, WorkSession, utcnow
from app.services.duration import effective_duration_seconds
from app.jira.worklogs import normalize_time_spent


@dataclass
class EnqueueResult:
    items: list[Outbox] = field(default_factory=list)
    duration_seconds: int = 0
    rounded_up: bool = False


def enqueue_session_push(
    db: Session, session: WorkSession, *, transition_to: str | None = None
) -> EnqueueResult:
    """Enqueue outbox items for a just-completed session.

    Enqueues a worklog, an optional comment (if there are notes), and an optional
    transition (if ``transition_to`` is given, section 5.6). Idempotent at the
    call site's discretion: callers should only call this once per completion,
    but calling it again is safe, it simply enqueues duplicate items (there is no
    unique constraint here by design, since a session could legitimately be
    completed, reopened, and completed again in a future phase).
    """
    raw_duration = effective_duration_seconds(
        session.started_at, session.ended_at, session.paused_seconds, session.adjusted_seconds
    )
    time_spent, rounded_up = normalize_time_spent(raw_duration)

    if not session.issue_key:
        return EnqueueResult(items=[], duration_seconds=time_spent, rounded_up=rounded_up)

    now = utcnow()
    items: list[Outbox] = [
        Outbox(
            session_id=session.id,
            kind="worklog",
            payload={
                "issue_key": session.issue_key,
                "started": session.started_at.isoformat(),
                "time_spent_seconds": time_spent,
                "comment_text": session.notes or None,
            },
            state="pending",
            attempts=0,
            next_attempt_at=now,
        )
    ]
    if session.notes:
        items.append(
            Outbox(
                session_id=session.id,
                kind="comment",
                payload={
                    "issue_key": session.issue_key,
                    "body_text": session.notes,
                    "around": now.isoformat(),
                },
                state="pending",
                attempts=0,
                next_attempt_at=now,
            )
        )

    if transition_to:
        items.append(
            Outbox(
                session_id=session.id,
                kind="transition",
                payload={
                    "issue_key": session.issue_key,
                    "target_name": transition_to,
                },
                state="pending",
                attempts=0,
                next_attempt_at=now,
            )
        )

    for item in items:
        db.add(item)
    db.commit()
    for item in items:
        db.refresh(item)

    return EnqueueResult(items=items, duration_seconds=time_spent, rounded_up=rounded_up)


def pending_or_failed_for_session(db: Session, session_id: int) -> list[Outbox]:
    stmt = (
        select(Outbox)
        .where(Outbox.session_id == session_id)
        .order_by(Outbox.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())
