"""Insights, git<->time reconciliation, and data export.

    GET /api/insights?from=&to=&preset=   -> analytics over a range
    GET /api/reconcile?from=&to=&preset=  -> commits vs logged time per ticket
    GET /api/export/backup                -> download the SQLite DB file
    GET /api/export/timesheet.csv?from=&to= -> completed sessions as CSV

All local and deterministic (no Jira). Range resolves from an explicit
from/to (ISO) or a named preset; preset defaults to the current week.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    InsightBucketOut,
    InsightsOut,
    ReconcileOut,
    ReconcileRowOut,
)
from app.services.export import backup_db_path, timesheet_csv
from app.services.insights import compute_insights, range_from_preset
from app.services.reconcile import reconcile

router = APIRouter(prefix="/api", tags=["insights"])


def _resolve_range(
    from_: datetime | None, to: datetime | None, preset: str | None
) -> tuple[datetime, datetime]:
    """Explicit from/to wins; else a named preset; else the current week."""
    if from_ and to:
        # Normalise to aware UTC so comparisons against stored UTC are valid.
        f = from_ if from_.tzinfo else from_.replace(tzinfo=timezone.utc)
        t = to if to.tzinfo else to.replace(tzinfo=timezone.utc)
        return f, t
    return range_from_preset(preset or "week")


def _bucket_out(b) -> InsightBucketOut:
    return InsightBucketOut(
        key=b.key,
        label=b.label,
        tracked_seconds=b.tracked_seconds,
        logged_seconds=b.logged_seconds,
        session_count=b.session_count,
    )


@router.get("/insights", response_model=InsightsOut)
def insights(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
) -> InsightsOut:
    start, end = _resolve_range(from_, to, preset)
    ins = compute_insights(db, start, end)
    return InsightsOut(
        range_start=ins.range_start,
        range_end=ins.range_end,
        total_tracked_seconds=ins.total_tracked_seconds,
        total_logged_seconds=ins.total_logged_seconds,
        session_count=ins.session_count,
        ticket_count=ins.ticket_count,
        by_project=[_bucket_out(b) for b in ins.by_project],
        by_type=[_bucket_out(b) for b in ins.by_type],
        by_ticket=[_bucket_out(b) for b in ins.by_ticket],
        by_day=[_bucket_out(b) for b in ins.by_day],
    )


@router.get("/reconcile", response_model=ReconcileOut)
def reconcile_route(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
) -> ReconcileOut:
    start, end = _resolve_range(from_, to, preset)
    rows = reconcile(db, start, end)
    return ReconcileOut(
        range_start=start.date().isoformat(),
        range_end=end.date().isoformat(),
        rows=[
            ReconcileRowOut(
                issue_key=r.issue_key,
                commit_count=r.commit_count,
                logged_seconds=r.logged_seconds,
                flag=r.flag,
            )
            for r in rows
        ],
    )


@router.get("/export/backup")
def export_backup() -> FileResponse:
    path = backup_db_path()
    if not path:
        raise HTTPException(status_code=400, detail="Backup is only supported for a SQLite database.")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename="jira-tracker-backup.db",
    )


@router.get("/export/timesheet.csv")
def export_timesheet(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    start, end = _resolve_range(from_, to, preset)
    csv_text = timesheet_csv(db, start, end)
    fname = f"timesheet_{start.date().isoformat()}_{end.date().isoformat()}.csv"
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
