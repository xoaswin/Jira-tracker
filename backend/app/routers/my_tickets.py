"""My Tickets + Plan-my-day routes.

    GET /api/my-tickets           -> my open tickets + overdue/due/soon counts
    GET /api/plan/today           -> ranked plan fitted to a capacity budget

Both are live from Jira (assignee = currentUser()); the plan additionally uses
locally-learned velocity. Jira's real error body surfaces on failure.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DayIntention
from app.schemas import (
    DayIntentionIn,
    DayIntentionOut,
    DayPlanOut,
    MyTicketOut,
    MyTicketsOut,
    PlanItemOut,
    TypeVelocityOut,
)
from app.services.connection import build_client
from app.services.my_tickets import get_my_tickets
from app.services.planning import build_day_plan
from app.services.tz import app_tz

router = APIRouter(prefix="/api", tags=["my-tickets"])


@router.get("/my-tickets", response_model=MyTicketsOut)
def my_tickets(db: Session = Depends(get_db)) -> MyTicketsOut:
    with build_client(db) as client:
        tickets = get_my_tickets(client, tz=app_tz(db))
    out = [MyTicketOut(**t.__dict__) for t in tickets]
    return MyTicketsOut(
        tickets=out,
        overdue=sum(1 for t in tickets if t.urgency == "overdue"),
        due_today=sum(1 for t in tickets if t.urgency == "due_today"),
        due_soon=sum(1 for t in tickets if t.urgency == "due_soon"),
    )


@router.get("/plan/today", response_model=DayPlanOut)
def plan_today(
    capacity_hours: float = Query(6.0, ge=0, le=24),
    db: Session = Depends(get_db),
) -> DayPlanOut:
    with build_client(db) as client:
        plan = build_day_plan(db, client, capacity_hours=capacity_hours)
    return DayPlanOut(
        capacity_seconds=plan.capacity_seconds,
        planned_seconds=plan.planned_seconds,
        overflow_seconds=plan.overflow_seconds,
        fitted_count=plan.fitted_count,
        total_samples=plan.velocity.total_samples,
        items=[
            PlanItemOut(
                ticket=MyTicketOut(**item.ticket.__dict__),
                estimate_seconds=item.estimate_seconds,
                fits=item.fits,
                cumulative_seconds=item.cumulative_seconds,
            )
            for item in plan.items
        ],
        velocity_by_type=[
            TypeVelocityOut(
                issue_type=tv.issue_type,
                sample_count=tv.sample_count,
                avg_seconds=tv.avg_seconds,
                median_seconds=tv.median_seconds,
            )
            for tv in plan.velocity.by_type.values()
        ],
    )


# --- start-of-day intention (the user's own plan; no Jira call needed) ---
#
# This is deliberately decoupled from sessions and from the live /plan/today
# ranking: it's what YOU said you'd work on, stored per local date, so the
# desktop check-in can nudge against it and it survives even when no timer is
# running.


@router.get("/plan/intention", response_model=DayIntentionOut | None)
def get_intention(
    date: str = Query(..., description="Local date YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> DayIntention | None:
    return db.query(DayIntention).filter_by(plan_date=date).one_or_none()


@router.post("/plan/intention", response_model=DayIntentionOut)
def upsert_intention(
    payload: DayIntentionIn,
    db: Session = Depends(get_db),
) -> DayIntention:
    row = db.query(DayIntention).filter_by(plan_date=payload.plan_date).one_or_none()
    if row is None:
        row = DayIntention(plan_date=payload.plan_date)
        db.add(row)
    row.note = payload.note
    row.ticket_keys = payload.ticket_keys
    db.commit()
    db.refresh(row)
    return row
