"""Activity routes (desktop recorder, zero-click tracking, timeline, focus).

    POST /api/activity/segments        <- recorder batches; returns auto-track suggestion
    POST /api/activity/autotrack       -> start/switch to a ticket as an auto session
    POST /api/activity/autotrack/undo  -> discard it (and pause auto-track on that key)
    POST /api/activity/away            -> pause on idle/lock, resume on return
    GET  /api/activity/day?date=       -> timeline for one day
    GET  /api/activity/focus?days=7    -> focus radar
    DELETE /api/activity               -> forget all recorded activity
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import activity
from app.services.focus import focus_report
from app.services.timeline import day_timeline

router = APIRouter(prefix="/api/activity", tags=["activity"])


class SegmentIn(BaseModel):
    start: datetime
    end: datetime
    app: str = ""
    title: str = ""
    kind: str = "active"


class SegmentsIn(BaseModel):
    segments: list[SegmentIn] = Field(default_factory=list)


class AutoTrackIn(BaseModel):
    issue_key: str


class UndoIn(BaseModel):
    session_id: int


class AwayIn(BaseModel):
    away: bool


@router.post("/segments")
def post_segments(req: SegmentsIn, db: Session = Depends(get_db)) -> dict:
    stored = activity.ingest(db, [activity.SegmentIn(**s.model_dump()) for s in req.segments])
    return {"stored": stored, "suggestion": activity.suggest(db)}


@router.post("/autotrack")
def post_autotrack(req: AutoTrackIn, db: Session = Depends(get_db)) -> dict:
    return activity.autotrack(db, req.issue_key)


@router.post("/autotrack/undo")
def post_undo(req: UndoIn, db: Session = Depends(get_db)) -> dict:
    return activity.undo_autotrack(db, req.session_id)


@router.post("/away")
def post_away(req: AwayIn, db: Session = Depends(get_db)) -> dict:
    return activity.set_away(db, req.away)


@router.get("/day")
def get_day(date_: date | None = Query(None, alias="date"), db: Session = Depends(get_db)) -> dict:
    return day_timeline(db, date_)


@router.get("/focus")
def get_focus(days: int = Query(7, ge=1, le=31), db: Session = Depends(get_db)) -> dict:
    return focus_report(db, days)


@router.delete("")
def clear_activity(db: Session = Depends(get_db)) -> dict:
    from app.models import ActivitySegment

    deleted = db.query(ActivitySegment).delete()
    db.commit()
    return {"deleted": deleted}
