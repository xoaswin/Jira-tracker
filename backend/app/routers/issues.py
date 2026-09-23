"""Issue drafting and creation routes (Phase 4, section 10).

    POST /api/issues/draft  -> draft summary/description + required fields +
                               duplicate warning (READ ONLY, no Jira write)
    POST /api/issues        -> create the confirmed issue in Jira, cache it

Section 15 rule 1: the only Jira write here is POST /api/issues, and the UI must
have shown the drafted issue and required one confirmation click first. The draft
endpoint never writes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    CreateIssueRequest,
    CreateIssueResponse,
    DraftRequest,
    DraftResponse,
    DuplicateWarningOut,
    IssueOut,
    RequiredFieldOut,
)
from app.services.connection import build_client
from app.services.drafting import build_draft
from app.services.issue_create import create_and_cache

router = APIRouter(prefix="/api/issues", tags=["issues"])


@router.post("/draft", response_model=DraftResponse)
def draft_issue(req: DraftRequest, db: Session = Depends(get_db)) -> DraftResponse:
    with build_client(db) as client:
        try:
            draft = build_draft(
                db,
                client,
                board_id=req.board_id,
                text=req.text,
                type_hint=req.type_hint,
                parent_key=req.parent_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DraftResponse(
        project_key=draft.project_key,
        issue_type=draft.issue_type,
        summary=draft.summary,
        description=draft.description,
        parent_key=draft.parent_key,
        required_fields=[
            RequiredFieldOut(
                field_id=f.field_id,
                name=f.name,
                schema_type=f.schema_type,
                allowed_values=f.allowed_values,
            )
            for f in draft.required_fields
        ],
        duplicate=(
            DuplicateWarningOut(
                issue_key=draft.duplicate.issue_key,
                summary=draft.duplicate.summary,
                similarity=draft.duplicate.similarity,
            )
            if draft.duplicate
            else None
        ),
    )


@router.post("", response_model=CreateIssueResponse)
def create_issue_route(req: CreateIssueRequest, db: Session = Depends(get_db)) -> CreateIssueResponse:
    # A subtask must have a parent (section 5.5). Fail loudly before hitting Jira.
    if req.type.strip().lower() in {"sub-task", "subtask"} and not req.parent_key:
        raise HTTPException(
            status_code=400,
            detail="A sub-task requires a parent issue key.",
        )

    with build_client(db) as client:
        issue = create_and_cache(
            db,
            client,
            board_id=req.board_id,
            project_key=req.project_key,
            issue_type_name=req.type,
            summary=req.summary,
            description=req.description,
            parent_key=req.parent_key,
            extra_fields=req.fields,
        )

    return CreateIssueResponse(issue_key=issue.issue_key, issue=IssueOut.model_validate(issue))
