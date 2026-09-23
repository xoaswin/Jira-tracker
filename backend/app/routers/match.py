"""Matching and git-context routes (Phase 3, section 10).

    POST /api/match      { board_id, text, branch_key? } -> ranked candidates
    GET  /api/git/context                                -> current branch chip

Matching is local, deterministic, and never calls Jira (section 6), so these
routes work offline and never block on the network.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AppSettings, Board
from app.schemas import (
    GitContextOut,
    MatchCandidate,
    MatchRequest,
    MatchResponse,
)
from app.services.git_context import current_git_context
from app.services.matching import match_boards_issues

router = APIRouter(prefix="/api", tags=["matching"])


@router.post("/match", response_model=MatchResponse)
def match(req: MatchRequest, db: Session = Depends(get_db)) -> MatchResponse:
    # Resolve the board set: an explicit board_ids list wins, else the single
    # board_id. At least one must be given.
    board_ids = req.board_ids if req.board_ids else (
        [req.board_id] if req.board_id is not None else []
    )
    if not board_ids:
        raise HTTPException(
            status_code=400, detail="Provide board_id or board_ids to match against."
        )
    # Deduplicate while preserving order, and validate every board exists.
    seen: set[int] = set()
    resolved: list[int] = []
    for bid in board_ids:
        if bid in seen:
            continue
        seen.add(bid)
        if db.get(Board, bid) is None:
            raise HTTPException(status_code=404, detail=f"Board {bid} not found")
        resolved.append(bid)

    result = match_boards_issues(
        db, resolved, req.text, branch_key=req.branch_key
    )
    # The connected account id, to flag which candidates are the user's own.
    settings = db.get(AppSettings, 1)
    my_account_id = settings.account_id if settings else None
    candidates = [
        MatchCandidate(
            issue_key=sc.candidate.issue_key,
            summary=sc.candidate.summary,
            issue_type=sc.candidate.issue_type,
            status=sc.candidate.status,
            status_category=sc.candidate.status_category,
            sprint_name=sc.candidate.sprint_name,
            assignee_name=sc.candidate.assignee_name,
            is_mine=(
                my_account_id is not None
                and sc.candidate.assignee_account_id == my_account_id
            ),
            score=round(sc.score, 4),
            confidence_pct=sc.confidence_pct,
            bm25=sc.bm25,
            embedding=sc.embedding,
            recency=sc.recency,
            reason=sc.reason,
        )
        for sc in result.candidates
    ]
    return MatchResponse(
        candidates=candidates,
        used_embeddings=result.used_embeddings,
        forced_key=result.forced_key,
        lead_with_create=result.lead_with_create,
        preselect_top=result.preselect_top,
        searched_board_ids=resolved,
    )


@router.get("/git/context", response_model=GitContextOut)
def git_context() -> GitContextOut:
    ctx = current_git_context()
    if ctx is None:
        return GitContextOut(detected=False)
    if not ctx.ok:
        return GitContextOut(detected=False, repo_path=ctx.repo_path, error=ctx.error)
    return GitContextOut(
        detected=True,
        repo_path=ctx.repo_path,
        branch=ctx.branch,
        commits=ctx.commits,
        issue_key=ctx.issue_key,
        suggested_text=ctx.suggested_text,
    )
