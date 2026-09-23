"""Session lifecycle routes: the core of the app (section 10)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorkSession, utcnow
from app.schemas import (
    CompleteResult,
    ManualSessionCreate,
    SessionComplete,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from app.services.duration import effective_duration_seconds, live_elapsed_seconds
from app.sync.outbox import enqueue_session_push
from app.sync.worker import process_due_items

logger = __import__("logging").getLogger("jira_tracker.sessions")


def _maybe_stamp_actual_dates(db: Session, session: WorkSession) -> None:
    """Best-effort auto-stamp actual start/end on the ticket (opt-in setting).

    Runs after a completed session has an issue and time. Never raises: a failure
    here must never affect the completion response (the worklog already landed).
    """
    if not session.issue_key or session.ended_at is None:
        return
    from app.models import AppSettings

    row = db.get(AppSettings, 1)
    if not row or not getattr(row, "auto_actual_dates", False):
        return
    try:
        from app.services.auto_dates import apply_actual_dates
        from app.services.connection import build_client

        with build_client(db) as client:
            apply_actual_dates(
                client,
                session.issue_key,
                started_at=session.started_at,
                ended_at=session.ended_at,
            )
    except Exception:  # noqa: BLE001 - never let this break completion
        logger.info("auto-dates stamping skipped for session %s", session.id, exc_info=True)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

ACTIVE_STATES = ("active", "paused")


def _to_out(s: WorkSession) -> SessionOut:
    """Serialise a session, computing the elapsed seconds for display."""
    if s.state in ACTIVE_STATES:
        elapsed = live_elapsed_seconds(s.started_at, utcnow(), s.paused_seconds, s.state, s.paused_at)
    elif s.state == "completed":
        elapsed = effective_duration_seconds(
            s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
        )
    else:
        elapsed = None
    out = SessionOut.model_validate(s)
    out.elapsed_seconds = elapsed
    return out


def _get_or_404(db: Session, session_id: int) -> WorkSession:
    s = db.get(WorkSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return s


@router.post("", response_model=SessionOut)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)) -> SessionOut:
    s = WorkSession(
        description=payload.description,
        board_id=payload.board_id,
        started_at=utcnow(),
        state="active",
        paused_seconds=0,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.get("", response_model=list[SessionOut])
def list_sessions(
    state: str | None = None,
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    db: Session = Depends(get_db),
) -> list[SessionOut]:
    stmt = select(WorkSession)
    if state:
        stmt = stmt.where(WorkSession.state == state)
    if from_:
        stmt = stmt.where(WorkSession.started_at >= from_)
    if to:
        stmt = stmt.where(WorkSession.started_at <= to)
    stmt = stmt.order_by(WorkSession.started_at.desc())
    return [_to_out(s) for s in db.execute(stmt).scalars().all()]


@router.get("/active", response_model=SessionOut | None)
def active_session(db: Session = Depends(get_db)) -> SessionOut | None:
    stmt = (
        select(WorkSession)
        .where(WorkSession.state.in_(ACTIVE_STATES))
        .order_by(WorkSession.started_at.desc())
    )
    s = db.execute(stmt).scalars().first()
    return _to_out(s) if s else None


@router.patch("/{session_id}", response_model=SessionOut)
def update_session(
    session_id: int, payload: SessionUpdate, db: Session = Depends(get_db)
) -> SessionOut:
    s = _get_or_404(db, session_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.post("/{session_id}/pause", response_model=SessionOut)
def pause_session(session_id: int, db: Session = Depends(get_db)) -> SessionOut:
    s = _get_or_404(db, session_id)
    if s.state == "active":
        s.state = "paused"
        s.paused_at = utcnow()
        db.commit()
        db.refresh(s)
    return _to_out(s)


@router.post("/{session_id}/resume", response_model=SessionOut)
def resume_session(session_id: int, db: Session = Depends(get_db)) -> SessionOut:
    s = _get_or_404(db, session_id)
    if s.state == "paused" and s.paused_at is not None:
        s.paused_seconds = (s.paused_seconds or 0) + int((utcnow() - s.paused_at).total_seconds())
        s.paused_at = None
        s.state = "active"
        db.commit()
        db.refresh(s)
    return _to_out(s)


@router.post("/{session_id}/complete", response_model=CompleteResult)
def complete_session(
    session_id: int, payload: SessionComplete, db: Session = Depends(get_db)
) -> CompleteResult:
    s = _get_or_404(db, session_id)

    # Fold any in-progress pause into paused_seconds before closing.
    now = utcnow()
    if s.state == "paused" and s.paused_at is not None:
        s.paused_seconds = (s.paused_seconds or 0) + int((now - s.paused_at).total_seconds())
        s.paused_at = None

    if payload.notes is not None:
        s.notes = payload.notes
    if payload.adjusted_seconds is not None:
        s.adjusted_seconds = payload.adjusted_seconds
    if payload.issue_key is not None:
        s.issue_key = payload.issue_key

    s.ended_at = now
    s.state = "completed"
    db.commit()
    db.refresh(s)

    # Phase 2: enqueue durable outbox items instead of pushing directly. The
    # session is already saved, so it is never lost (rule 2). We then kick the
    # worker once, synchronously, so that on a healthy network the worklog lands
    # immediately (preserving the Phase 1 "logged to Jira" UX); if the network is
    # down or Jira rejects it, the item stays queued and is retried later by the
    # background worker.
    enqueue = enqueue_session_push(db, s, transition_to=payload.transition_to)
    duration = enqueue.duration_seconds
    rounded = enqueue.rounded_up

    if not enqueue.items:
        # No issue selected; there is nothing to push against (rule 2: still saved).
        s.sync_state = "unsynced"
        s.sync_error = "No issue selected; nothing was pushed to Jira."
        db.commit()
        db.refresh(s)
        return CompleteResult(
            session=_to_out(s),
            duration_seconds=duration,
            rounded_up=rounded,
            warning="No issue selected, so no worklog was pushed.",
        )

    process_due_items(db)
    db.refresh(s)
    _maybe_stamp_actual_dates(db, s)

    if s.sync_state == "synced":
        warning = (
            "Session was under a minute, so it was rounded up to 60 seconds."
            if rounded
            else None
        )
    elif s.sync_state == "error":
        warning = f"Push to Jira failed: {s.sync_error}"
    else:
        # Still pending: not connected, a retryable failure, or needs reauth.
        # Durable in the outbox and will retry, so reassure rather than alarm.
        warning = (
            s.sync_error
            or "Saved locally; will sync to Jira automatically when possible."
        )

    return CompleteResult(
        session=_to_out(s),
        duration_seconds=duration,
        rounded_up=rounded,
        warning=warning,
    )


@router.post("/{session_id}/repush", response_model=SessionOut)
def repush_session_route(session_id: int, db: Session = Depends(get_db)) -> SessionOut:
    """Re-sync an edited completed session to Jira without duplicating a worklog.

    Use after PATCHing a completed session's issue_key / notes / adjusted_seconds
    on the Dashboard. Updates the existing worklog in place when already synced,
    else enqueues a fresh push.
    """
    from app.services.repush import repush_session

    s = _get_or_404(db, session_id)
    repush_session(db, s)
    db.refresh(s)
    return _to_out(s)


@router.post("/manual", response_model=CompleteResult)
def create_manual_session(payload: ManualSessionCreate, db: Session = Depends(get_db)) -> CompleteResult:
    """Log a completed session for past work, without a live timer.

    Creates a session that is already completed with an explicit duration and a
    chosen start time, then pushes it through the durable outbox exactly like a
    normally-finished session.
    """
    now = utcnow()
    started = payload.started_at or now
    s = WorkSession(
        description=payload.description,
        board_id=payload.board_id,
        issue_key=payload.issue_key,
        started_at=started,
        ended_at=started,  # duration comes from adjusted_seconds, not the clock
        paused_seconds=0,
        adjusted_seconds=max(0, int(payload.duration_seconds)),
        state="completed",
        issue_origin="manual",
        notes=payload.notes,
        created_at=now,
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    enqueue = enqueue_session_push(db, s, transition_to=payload.transition_to)
    duration = enqueue.duration_seconds
    rounded = enqueue.rounded_up

    if not enqueue.items:
        s.sync_state = "unsynced"
        s.sync_error = "No issue selected; nothing was pushed to Jira."
        db.commit()
        db.refresh(s)
        return CompleteResult(
            session=_to_out(s),
            duration_seconds=duration,
            rounded_up=rounded,
            warning="No issue selected, so no worklog was pushed.",
        )

    process_due_items(db)
    db.refresh(s)
    _maybe_stamp_actual_dates(db, s)
    warning = None if s.sync_state == "synced" else (
        s.sync_error or "Saved locally; will sync to Jira automatically when possible."
    )
    return CompleteResult(
        session=_to_out(s),
        duration_seconds=duration,
        rounded_up=rounded,
        warning=warning,
    )


@router.delete("/{session_id}", response_model=SessionOut)
def abandon_session(session_id: int, db: Session = Depends(get_db)) -> SessionOut:
    s = _get_or_404(db, session_id)
    s.state = "abandoned"
    if s.ended_at is None:
        s.ended_at = utcnow()
    db.commit()
    db.refresh(s)
    return _to_out(s)
