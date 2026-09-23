"""Board caching: refresh from Jira and read back from SQLite."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jira.boards import (
    get_board_configuration,
    list_boards,
    normalize_board,
    resolve_project_from_configuration,
)
from app.jira.client import JiraClient, JiraError
from app.models import Board, utcnow

logger = logging.getLogger("jira_tracker.boards_sync")


def refresh_boards(db: Session, client: JiraClient) -> list[Board]:
    """Fetch all boards from Jira and upsert them, preserving favourites."""
    raw_boards = list_boards(client)
    now = utcnow()
    for raw in raw_boards:
        data = normalize_board(raw)
        if data["id"] is None:
            continue
        # If the board object didn't carry a project, try its configuration.
        if not data["project_key"]:
            try:
                config = get_board_configuration(client, data["id"])
                resolved = resolve_project_from_configuration(config)
                data["project_key"] = resolved["project_key"] or data["project_key"]
                data["project_id"] = resolved["project_id"] or data["project_id"]
            except JiraError as exc:
                # A board we can't read config for is still listable; log and move on.
                logger.warning("board %s configuration unavailable: %s", data["id"], exc)

        board = db.get(Board, data["id"])
        if board is None:
            board = Board(id=data["id"], is_favourite=False)
            db.add(board)
        board.name = data["name"]
        board.type = data["type"]
        board.project_key = data["project_key"]
        board.project_id = data["project_id"]
        board.last_synced_at = now
    db.commit()
    return list_cached_boards(db)


def list_cached_boards(db: Session) -> list[Board]:
    """Favourites pinned first, then alphabetical (section 11)."""
    stmt = select(Board).order_by(Board.is_favourite.desc(), Board.name.asc())
    return list(db.execute(stmt).scalars().all())


def toggle_favourite(db: Session, board_id: int) -> Board | None:
    board = db.get(Board, board_id)
    if board is None:
        return None
    board.is_favourite = not board.is_favourite
    db.commit()
    db.refresh(board)
    return board
