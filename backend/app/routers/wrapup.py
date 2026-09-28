"""End-of-day wrap-up routes (see ``app.services.wrapup``).

    GET  /api/wrapup/today              -> today's sessions + totals (app timezone)
    POST /api/wrapup/draft/{session_id} -> worklog comment drafted from git/notes
    POST /api/wrapup/log                -> log the given sessions to Jira
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorkSession
from app.schemas import WrapupDayOut, WrapupDraftOut, WrapupLogOutcome, WrapupLogRequest
from app.services.wrapup import draft_comment, log_sessions, today_wrapup

router = APIRouter(prefix="/api/wrapup", tags=["wrapup"])


@router.get("/today", response_model=WrapupDayOut)
def wrapup_today(db: Session = Depends(get_db)) -> WrapupDayOut:
    return WrapupDayOut(**asdict(today_wrapup(db)))


@router.post("/draft/{session_id}", response_model=WrapupDraftOut)
def wrapup_draft(session_id: int, db: Session = Depends(get_db)) -> WrapupDraftOut:
    s = db.get(WorkSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return WrapupDraftOut(**asdict(draft_comment(db, s)))


@router.post("/log", response_model=list[WrapupLogOutcome])
def wrapup_log(req: WrapupLogRequest, db: Session = Depends(get_db)) -> list[WrapupLogOutcome]:
    items = [i.model_dump() for i in req.items]
    return [WrapupLogOutcome(**asdict(o)) for o in log_sessions(db, items)]
