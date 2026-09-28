"""The user's working timezone (settings.timezone, an IANA name).

Storage stays UTC everywhere; this only decides which calendar day an instant
belongs to (report/insight day buckets, "today" for summaries and plans). The
machine clock is deliberately NOT used: the user's Jira work is tracked in IST
even when the laptop's clock is set to another zone.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

logger = logging.getLogger("jira_tracker.tz")

DEFAULT_TIMEZONE = "Asia/Kolkata"
# IST has no DST, so a fixed offset is an exact fallback if tzdata is missing.
_IST_FIXED = timezone(timedelta(hours=5, minutes=30), "IST")


def zone(name: str | None) -> tzinfo:
    """Resolve an IANA name, falling back to IST on unknown/missing data."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("unknown timezone %r, falling back to IST", name)
        return _IST_FIXED


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def app_tz(db: Session) -> tzinfo:
    from app.services.connection import get_settings_row

    row = get_settings_row(db)
    return zone(getattr(row, "timezone", None) if row else None)


def today(tz: tzinfo) -> date:
    return datetime.now(tz).date()


def local_day(dt: datetime, tz: tzinfo) -> date:
    """The calendar day ``dt`` falls on in ``tz`` (naive = UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def day_bounds(a: date, b: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start of ``a``, end of ``b``] in ``tz``, as aware UTC instants."""
    start = datetime.combine(a, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(b, time.max, tzinfo=tz).astimezone(timezone.utc)
    return start, end
