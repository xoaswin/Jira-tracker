"""Ticket management routes (Manage screen).

    GET  /api/manage/{key}                 -> status, transitions, dates, subtasks
    PATCH/api/manage/{key}/dates           -> edit editable date fields
    POST /api/manage/{key}/transition      -> auto-walk this issue to a status
    POST /api/manage/{key}/done            -> mark done (blocked if subtasks open)
    POST /api/manage/{key}/subtasks/{sk}/transition -> walk a subtask to a status

All of these talk to live Jira. Errors surface Jira's real body (rule 8).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    AddWorklogRequest,
    AddWorklogResult,
    AssignableUserOut,
    CreateSubtaskRequest,
    EditDatesRequest,
    ManageViewOut,
    PriorityOut,
    SetAssigneeRequest,
    SetPriorityRequest,
    TransitionRequest,
    TransitionResult,
    WorklogEntryOut,
)
from app.services.connection import build_client
from app.services.manage import (
    NoTimeError,
    SubtaskCreateError,
    SubtasksIncompleteError,
    create_subtask,
    edit_dates,
    get_manage_view,
    list_worklogs,
    log_work,
    mark_done,
    transition_subtask,
)
from app.jira.people import (
    list_priorities,
    search_assignable_users,
    set_assignee,
    set_priority,
)
from app.jira.transitions import walk_to_status

router = APIRouter(prefix="/api/manage", tags=["manage"])


def _view_out(view) -> ManageViewOut:
    return ManageViewOut(
        issue_key=view.issue_key,
        summary=view.summary,
        issue_type=view.issue_type,
        status=view.status,
        status_category=view.status_category,
        assignee_account_id=view.assignee_account_id,
        assignee_name=view.assignee_name,
        priority_id=view.priority_id,
        priority_name=view.priority_name,
        available_transitions=view.available_transitions,
        date_fields=view.date_fields,
        subtasks=[st.__dict__ for st in view.subtasks],
    )


@router.get("/{issue_key}", response_model=ManageViewOut)
def manage_view(issue_key: str, db: Session = Depends(get_db)) -> ManageViewOut:
    with build_client(db) as client:
        return _view_out(get_manage_view(client, issue_key))


@router.patch("/{issue_key}/dates", response_model=ManageViewOut)
def edit_dates_route(
    issue_key: str, req: EditDatesRequest, db: Session = Depends(get_db)
) -> ManageViewOut:
    with build_client(db) as client:
        edit_dates(client, issue_key, req.values)
        return _view_out(get_manage_view(client, issue_key))


@router.post("/{issue_key}/transition", response_model=TransitionResult)
def transition_route(
    issue_key: str, req: TransitionRequest, db: Session = Depends(get_db)
) -> TransitionResult:
    with build_client(db) as client:
        applied = walk_to_status(client, issue_key, req.target)
        return TransitionResult(applied=applied, view=_view_out(get_manage_view(client, issue_key)))


@router.post("/{issue_key}/done", response_model=TransitionResult)
def done_route(issue_key: str, db: Session = Depends(get_db)) -> TransitionResult:
    with build_client(db) as client:
        try:
            applied = mark_done(client, issue_key)
        except SubtasksIncompleteError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Cannot mark Done: some subtasks are not Done.",
                    "pending_subtasks": exc.pending,
                    "code": "subtasks_incomplete",
                },
            ) from exc
        return TransitionResult(applied=applied, view=_view_out(get_manage_view(client, issue_key)))


@router.post("/{issue_key}/subtasks/{subtask_key}/transition", response_model=TransitionResult)
def subtask_transition_route(
    issue_key: str,
    subtask_key: str,
    req: TransitionRequest,
    db: Session = Depends(get_db),
) -> TransitionResult:
    with build_client(db) as client:
        applied = transition_subtask(client, subtask_key, req.target)
        # Return the PARENT view so the UI can refresh subtask states + the
        # parent's Done-button gating in one round trip.
        return TransitionResult(applied=applied, view=_view_out(get_manage_view(client, issue_key)))


@router.get("/{issue_key}/worklogs", response_model=list[WorklogEntryOut])
def worklogs_route(issue_key: str, db: Session = Depends(get_db)) -> list[WorklogEntryOut]:
    with build_client(db) as client:
        return [WorklogEntryOut(**w) for w in list_worklogs(client, issue_key)]


@router.post("/{issue_key}/worklog", response_model=AddWorklogResult)
def add_worklog_route(
    issue_key: str, req: AddWorklogRequest, db: Session = Depends(get_db)
) -> AddWorklogResult:
    from app.models import AppSettings

    settings = db.get(AppSettings, 1)
    account_id = settings.account_id if settings else None
    with build_client(db) as client:
        try:
            worklog, rounded_up = log_work(
                client,
                issue_key,
                hours=req.hours,
                minutes=req.minutes,
                started=req.started,
                comment=req.comment,
                account_id=account_id,
            )
        except NoTimeError as exc:
            raise HTTPException(
                status_code=422,
                detail={"message": str(exc), "code": "no_time"},
            ) from exc
        from app.services.manage import _worklog_view

        return AddWorklogResult(
            worklog=WorklogEntryOut(**_worklog_view(worklog)), rounded_up=rounded_up
        )


@router.get("/{issue_key}/assignable", response_model=list[AssignableUserOut])
def assignable_users_route(
    issue_key: str, q: str = "", db: Session = Depends(get_db)
) -> list[AssignableUserOut]:
    with build_client(db) as client:
        return [AssignableUserOut(**u) for u in search_assignable_users(client, issue_key, q)]


@router.get("/{issue_key}/priorities", response_model=list[PriorityOut])
def priorities_route(issue_key: str, db: Session = Depends(get_db)) -> list[PriorityOut]:
    # issue_key is unused (priorities are global) but keeps the URL consistent
    # and future-proofs per-project priority schemes.
    with build_client(db) as client:
        return [PriorityOut(**p) for p in list_priorities(client)]


@router.put("/{issue_key}/assignee", response_model=ManageViewOut)
def set_assignee_route(
    issue_key: str, req: SetAssigneeRequest, db: Session = Depends(get_db)
) -> ManageViewOut:
    with build_client(db) as client:
        set_assignee(client, issue_key, req.account_id)
        return _view_out(get_manage_view(client, issue_key))


@router.put("/{issue_key}/priority", response_model=ManageViewOut)
def set_priority_route(
    issue_key: str, req: SetPriorityRequest, db: Session = Depends(get_db)
) -> ManageViewOut:
    with build_client(db) as client:
        set_priority(client, issue_key, req.priority_id)
        return _view_out(get_manage_view(client, issue_key))


@router.post("/{issue_key}/subtasks", response_model=ManageViewOut)
def create_subtask_route(
    issue_key: str, req: CreateSubtaskRequest, db: Session = Depends(get_db)
) -> ManageViewOut:
    """Create a sub-task under this issue, then return the refreshed parent view
    so the new subtask shows up immediately."""
    with build_client(db) as client:
        try:
            create_subtask(db, client, issue_key, req.summary)
        except SubtaskCreateError as exc:
            raise HTTPException(
                status_code=400, detail={"message": str(exc), "code": "subtask_create"}
            ) from exc
        return _view_out(get_manage_view(client, issue_key))
