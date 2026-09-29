"""Focus radar: deep-work blocks, context switching and long days from the
recorded activity, with plain rule-based suggestions (no AI needed)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivitySegment, AppSettings, WorkSession, utcnow
from app.services.activity import category
from app.services.timeline import session_span
from app.services.tz import app_tz, day_bounds

DEEP_MIN = timedelta(minutes=25)       # a focus block must last this long...
INTERRUPT_MAX = timedelta(minutes=2)   # ...and may absorb interruptions this short
SWITCH_MIN = timedelta(seconds=30)     # glances shorter than this aren't switches
LONG_DAY_HOURS = 9


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _context(seg: ActivitySegment) -> str:
    # What you're "on": the ticket if known, else the app category/app.
    if seg.issue_key:
        return f"key:{seg.issue_key}"
    cat = category(seg.app)
    return f"cat:{cat}" if cat != "other" else f"app:{seg.app.lower()}"


def _day_stats(db: Session, day: date, tz, work_end_min: int | None) -> dict:
    start, end = day_bounds(day, day, tz)
    now = utcnow()
    end = min(end, now)
    segs = [
        s for s in db.execute(
            select(ActivitySegment)
            .where(ActivitySegment.ended_at > start, ActivitySegment.started_at < end)
            .order_by(ActivitySegment.started_at)
        ).scalars().all()
        if s.kind == "active"
    ]

    # Collapse into (context, start, end) runs, clipped to the day.
    runs: list[list] = []
    for s in segs:
        a, b = max(_aware(s.started_at), start), min(_aware(s.ended_at), end)
        if b <= a:
            continue
        ctx = _context(s)
        if runs and runs[-1][0] == ctx and a - runs[-1][2] <= timedelta(seconds=60):
            runs[-1][2] = max(runs[-1][2], b)
        else:
            runs.append([ctx, a, b])

    active = sum((b - a).total_seconds() for _, a, b in runs)
    meaningful = [r for r in runs if r[2] - r[1] >= SWITCH_MIN]
    switches = sum(1 for i in range(1, len(meaningful)) if meaningful[i][0] != meaningful[i - 1][0])

    # Deep blocks: same context, bridging short interruptions.
    deep: list[tuple[datetime, datetime, str]] = []
    cur = None  # [ctx, start, end]
    for ctx, a, b in runs:
        if cur and ctx == cur[0] and a - cur[2] <= INTERRUPT_MAX:
            cur[2] = b
            continue
        if cur and ctx != cur[0] and (b - a) <= INTERRUPT_MAX and a - cur[2] <= INTERRUPT_MAX:
            continue  # a brief interruption inside the current block
        if cur and cur[2] - cur[1] >= DEEP_MIN:
            deep.append((cur[1], cur[2], cur[0]))
        cur = [ctx, a, b]
    if cur and cur[2] - cur[1] >= DEEP_MIN:
        deep.append((cur[1], cur[2], cur[0]))

    tracked = 0
    for s in db.execute(
        select(WorkSession).where(
            WorkSession.state.in_(("active", "paused", "completed")),
            WorkSession.started_at >= start,
            WorkSession.started_at <= end,
        )
    ).scalars().all():
        tracked += session_span(s, now)[2]

    late = 0.0
    if work_end_min is not None:
        for _, a, b in runs:
            la, lb = a.astimezone(tz), b.astimezone(tz)
            cutoff = la.replace(hour=work_end_min // 60, minute=work_end_min % 60, second=0, microsecond=0)
            if lb > cutoff:
                late += (lb - max(la, cutoff)).total_seconds()

    deep_hours: dict[int, float] = {}
    for a, b, _ in deep:
        t = a
        while t < b:
            nxt = min(b, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
            h = t.astimezone(tz).hour
            deep_hours[h] = deep_hours.get(h, 0.0) + (nxt - t).total_seconds()
            t = nxt

    return {
        "date": day.isoformat(),
        "active_seconds": int(active),
        "tracked_seconds": int(tracked),
        "switches": switches,
        "switches_per_hour": round(switches / (active / 3600), 1) if active >= 1800 else None,
        "deep_blocks": len(deep),
        "deep_seconds": int(sum((b - a).total_seconds() for a, b, _ in deep)),
        "longest_deep_seconds": int(max(((b - a).total_seconds() for a, b, _ in deep), default=0)),
        "late_seconds": int(late),
        "_deep_hours": deep_hours,
    }


def focus_report(db: Session, days: int = 7) -> dict:
    tz = app_tz(db)
    today = utcnow().astimezone(tz).date()
    settings = db.get(AppSettings, 1)
    work_end = None
    if settings and settings.work_end_time:
        try:
            h, m = (int(x) for x in settings.work_end_time.split(":"))
            work_end = h * 60 + m
        except ValueError:
            work_end = None

    per_day = [_day_stats(db, today - timedelta(days=i), tz, work_end) for i in range(days - 1, -1, -1)]
    recorded = [d for d in per_day if d["active_seconds"] > 0]

    hour_totals: dict[int, float] = {}
    for d in per_day:
        for h, secs in d.pop("_deep_hours").items():
            hour_totals[h] = hour_totals.get(h, 0.0) + secs

    tips: list[str] = []
    if recorded:
        avg_switch = sum(d["switches"] for d in recorded) / len(recorded)
        deep_share = sum(d["deep_seconds"] for d in recorded) / max(1, sum(d["active_seconds"] for d in recorded))
        long_days = [d for d in recorded if d["active_seconds"] >= LONG_DAY_HOURS * 3600]
        late_days = [d for d in recorded if d["late_seconds"] >= 1800]
        if avg_switch >= 30:
            tips.append(f"You switch context about {round(avg_switch)} times a day. Batch Teams/Outlook into 2-3 fixed slots.")
        if deep_share < 0.3:
            tips.append(f"Only {round(deep_share * 100)}% of your active time is in 25+ minute focus blocks. Protect one 90-minute block a day.")
        if hour_totals:
            best = max(hour_totals, key=hour_totals.get)
            tips.append(f"Your deepest focus usually starts around {best:02d}:00. Keep that hour meeting-free.")
        if long_days:
            tips.append(f"{len(long_days)} day(s) ran over {LONG_DAY_HOURS}h of screen activity this week. Watch for burnout.")
        if late_days:
            tips.append(f"You worked 30+ minutes past your end time on {len(late_days)} day(s).")
        if not tips:
            tips.append("Healthy week: long focus blocks, few switches, sensible hours.")

    return {
        "days": per_day,
        "deep_by_hour": {str(h): int(v) for h, v in sorted(hour_totals.items())},
        "tips": tips,
        "recording": bool(recorded),
    }
