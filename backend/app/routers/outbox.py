"""Outbox routes: inspect and manually drive the durable write queue (section 10).

    GET    /api/outbox            -> pending and failed items, newest first
    POST   /api/outbox/{id}/retry -> re-queue one item and drain immediately
    POST   /api/outbox/retry-all  -> re-queue every not-done item and drain
    DELETE /api/outbox/{id}       -> give up on one item (marks it done-with-no-result)

Manual retry is the user override for the automatic backoff: it clears the item's
error, makes it due now, and kicks the worker synchronously so the UI reflects the
outcome on the same request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Outbox, utcnow
from app.schemas import OutboxActionResult, OutboxItemOut
from app.sync.worker import process_due_items, update_session_sync_state

router = APIRouter(prefix="/api/outbox", tags=["outbox"])

# States a user can still act on. "done" items are history, not actionable.
ACTIONABLE_STATES = ("pending", "failed")


def _to_out(item: Outbox) -> OutboxItemOut:
    out = OutboxItemOut.model_validate(item)
    payload = item.payload or {}
    out.issue_key = payload.get("issue_key")
    return out


def _get_or_404(db: Session, item_id: int) -> Outbox:
    item = db.get(Outbox, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Outbox item {item_id} not found")
    return item


def _requeue(item: Outbox) -> None:
    """Reset an item to fire immediately, clearing its failure state."""
    item.state = "pending"
    item.last_error = None
    item.next_attempt_at = utcnow()


@router.get("", response_model=list[OutboxItemOut])
def list_outbox(
    include_done: bool = False, db: Session = Depends(get_db)
) -> list[OutboxItemOut]:
    stmt = select(Outbox)
    if not include_done:
        stmt = stmt.where(Outbox.state.in_(ACTIONABLE_STATES))
    stmt = stmt.order_by(Outbox.created_at.desc())
    return [_to_out(i) for i in db.execute(stmt).scalars().all()]


@router.post("/{item_id}/retry", response_model=OutboxActionResult)
def retry_item(item_id: int, db: Session = Depends(get_db)) -> OutboxActionResult:
    item = _get_or_404(db, item_id)
    if item.state == "done":
        # Nothing to do; report it back as-is rather than re-sending.
        return OutboxActionResult(item=_to_out(item), processed=0)
    _requeue(item)
    db.commit()

    result = process_due_items(db)
    db.refresh(item)
    return OutboxActionResult(
        item=_to_out(item),
        processed=result.get("processed", 0),
        reason=result.get("reason"),
    )


@router.post("/retry-all", response_model=OutboxActionResult)
def retry_all(db: Session = Depends(get_db)) -> OutboxActionResult:
    items = list(
        db.execute(select(Outbox).where(Outbox.state.in_(ACTIONABLE_STATES)))
        .scalars()
        .all()
    )
    for item in items:
        _requeue(item)
    if items:
        db.commit()

    result = process_due_items(db)
    return OutboxActionResult(
        processed=result.get("processed", 0),
        reason=result.get("reason"),
    )


@router.delete("/{item_id}", response_model=OutboxItemOut)
def discard_item(item_id: int, db: Session = Depends(get_db)) -> OutboxItemOut:
    """Give up on an item. It is marked done (no Jira result) so it stops
    retrying and no longer flags the session; the user chose to abandon it."""
    item = _get_or_404(db, item_id)
    item.state = "done"
    item.last_error = None
    item.completed_at = utcnow()
    db.commit()
    if item.session_id:
        update_session_sync_state(db, item.session_id)
    db.refresh(item)
    return _to_out(item)
