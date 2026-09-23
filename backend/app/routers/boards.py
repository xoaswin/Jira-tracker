"""Board routes: list/refresh, favourite, and per-board issue cache (section 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Board
from app.schemas import BoardOut, IssueOut
from app.services.boards_sync import list_cached_boards, refresh_boards, toggle_favourite
from app.services.connection import build_client
from app.services.issues_sync import list_cached_issues, refresh_board_issues

router = APIRouter(prefix="/api/boards", tags=["boards"])


@router.get("", response_model=list[BoardOut])
def get_boards(refresh: bool = False, db: Session = Depends(get_db)) -> list[Board]:
    if refresh:
        with build_client(db) as client:
            refresh_boards(db, client)
    return list_cached_boards(db)


@router.post("/{board_id}/favourite", response_model=BoardOut)
def favourite(board_id: int, db: Session = Depends(get_db)) -> Board:
    board = toggle_favourite(db, board_id)
    if board is None:
        raise HTTPException(status_code=404, detail=f"Board {board_id} not found")
    return board


@router.get("/{board_id}/issues", response_model=list[IssueOut])
def get_issues(board_id: int, refresh: bool = False, db: Session = Depends(get_db)):
    if db.get(Board, board_id) is None:
        raise HTTPException(status_code=404, detail=f"Board {board_id} not found")
    if refresh:
        with build_client(db) as client:
            refresh_board_issues(db, client, board_id)
    return list_cached_issues(db, board_id)


def _bg_refresh_issues(board_id: int) -> None:
    """Background task body: its own DB session and client."""
    db = SessionLocal()
    try:
        with build_client(db) as client:
            refresh_board_issues(db, client, board_id)
    finally:
        db.close()


@router.post("/{board_id}/sync")
def sync_board(board_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(Board, board_id) is None:
        raise HTTPException(status_code=404, detail=f"Board {board_id} not found")
    # Kick a background refresh. FastAPI BackgroundTasks needs the response cycle;
    # for a single-user app a daemon thread is simpler and returns immediately.
    import threading

    threading.Thread(target=_bg_refresh_issues, args=(board_id,), daemon=True).start()
    return {"status": "started", "board_id": board_id}
