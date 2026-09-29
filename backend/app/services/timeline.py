"""One day, side by side: app activity, tracked sessions, git commits, and the
work window, for the timeline screen (drag a gap onto a ticket to log it)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.git import commits_between, extract_issue_key
from app.models import ActivitySegment, AppSettings, WorkSession, utcnow
from app.services.activity import category
from app.services.duration import effective_duration_seconds, live_elapsed_seconds
from app.services.repos import repo_paths
from app.services.tz import app_tz, day_bounds

# Consecutive segments of the same app/ticket closer than this become one block.
BLOCK_GAP = timedelta(seconds=60)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return _aware(dt).isoformat()


def session_span(s: WorkSession, now: datetime) -> tuple[datetime, datetime, int]:
    """(start, end, seconds) of a session as it should appear on a timeline.
    Manual entries store ended_at == started_at, so their end is start+duration."""
    start = _aware(s.started_at)
    if s.state in ("active", "paused"):
        secs = live_elapsed_seconds(s.started_at, now, s.paused_seconds, s.state, s.paused_at)
        return start, now, secs
    secs = effective_duration_seconds(s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds)
    end = _aware(s.ended_at) if s.ended_at else start
    if end - start < timedelta(seconds=secs) and s.issue_origin == "manual":
        end = start + timedelta(seconds=secs)
    return start, end, secs


def activity_blocks(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        select(ActivitySegment)
        .where(ActivitySegment.ended_at > start, ActivitySegment.started_at < end)
        .order_by(ActivitySegment.started_at)
    ).scalars().all()
    blocks: list[dict] = []
    for r in rows:
        a, b = max(_aware(r.started_at), start), min(_aware(r.ended_at), end)
        if b <= a:
            continue
        cat = "away" if r.kind != "active" else category(r.app)
        prev = blocks[-1] if blocks else None
        if (
            prev
            and prev["kind"] == r.kind
            and prev["app"] == r.app
            and prev["issue_key"] == r.issue_key
            and a - prev["_end"] <= BLOCK_GAP
        ):
            prev["_end"] = max(prev["_end"], b)
            prev["_titles"][r.title] = prev["_titles"].get(r.title, 0) + (b - a).total_seconds()
            continue
        blocks.append({
            "_start": a, "_end": b, "app": r.app, "kind": r.kind, "category": cat,
            "issue_key": r.issue_key, "_titles": {r.title: (b - a).total_seconds()},
        })
    out = []
    for blk in blocks:
        titles = blk.pop("_titles")
        a, b = blk.pop("_start"), blk.pop("_end")
        out.append({
            **blk,
            "start": a.isoformat(),
            "end": b.isoformat(),
            "seconds": int((b - a).total_seconds()),
            "title": max(titles, key=titles.get) if titles else "",
        })
    return out


def day_timeline(db: Session, day: date | None = None) -> dict:
    tz = app_tz(db)
    now = utcnow()
    day = day or now.astimezone(tz).date()
    start, end = day_bounds(day, day, tz)
    end = min(end, max(now, start))  # nothing in the future

    sessions = []
    for s in db.execute(
        select(WorkSession)
        .where(
            WorkSession.state.in_(("active", "paused", "completed")),
            WorkSession.started_at >= start - timedelta(hours=12),
            WorkSession.started_at <= end,
        )
        .order_by(WorkSession.started_at)
    ).scalars().all():
        a, b, secs = session_span(s, now)
        if b <= start or a >= end:
            continue
        sessions.append({
            "id": s.id, "issue_key": s.issue_key, "description": s.description,
            "state": s.state, "origin": s.issue_origin, "sync_state": s.sync_state,
            "start": _iso(max(a, start)), "end": _iso(min(b, end)), "seconds": secs,
        })

    commits = []
    for path in repo_paths(db):
        for at, subject in commits_between(path, start, end):
            commits.append({
                "at": at.isoformat(), "subject": subject, "repo": path,
                "issue_key": extract_issue_key(subject),
            })
    commits.sort(key=lambda c: c["at"])

    settings = db.get(AppSettings, 1)
    work = None
    if settings and settings.work_start_time and settings.work_end_time:
        try:
            sh, sm = (int(x) for x in settings.work_start_time.split(":"))
            eh, em = (int(x) for x in settings.work_end_time.split(":"))
            ws = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
            we = datetime(day.year, day.month, day.day, eh, em, tzinfo=tz)
            if we <= ws:
                we += timedelta(days=1)
            work = {"start": ws.isoformat(), "end": we.isoformat()}
        except ValueError:
            work = None

    blocks = activity_blocks(db, start, end)
    by_category: dict[str, int] = {}
    for blk in blocks:
        by_category[blk["category"]] = by_category.get(blk["category"], 0) + blk["seconds"]

    return {
        "date": day.isoformat(),
        "day_start": start.isoformat(),
        "day_end": _iso(day_bounds(day, day, tz)[1]),
        "now": now.isoformat(),
        "work": work,
        "activity": blocks,
        "sessions": sessions,
        "commits": commits,
        "by_category": by_category,
        "recording": bool(blocks) or db.execute(select(ActivitySegment.id).limit(1)).first() is not None,
    }
