"""Velocity route: how long a ticket of a given type usually takes you.

    GET /api/velocity/estimate?issue_type=Bug  -> estimate + sample confidence

Local and deterministic (no Jira). Used by the mid-session over-budget warning
and could back estimate hints elsewhere.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import EstimateOut
from app.services.velocity import compute_velocity

router = APIRouter(prefix="/api/velocity", tags=["velocity"])


@router.get("/estimate", response_model=EstimateOut)
def estimate(
    issue_type: str | None = Query(None),
    db: Session = Depends(get_db),
) -> EstimateOut:
    vel = compute_velocity(db)
    seconds = vel.estimate_seconds(issue_type)

    # Report what the estimate is grounded in, so the UI can calibrate its tone.
    if issue_type and issue_type in vel.by_type and vel.by_type[issue_type].sample_count > 0:
        based_on = "type"
        sample_count = vel.by_type[issue_type].sample_count
    elif vel.total_samples > 0:
        based_on = "overall"
        sample_count = vel.total_samples
    else:
        based_on = "default"
        sample_count = 0

    return EstimateOut(
        issue_type=issue_type,
        estimate_seconds=seconds,
        sample_count=sample_count,
        based_on=based_on,
    )
