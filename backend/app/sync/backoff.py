"""Backoff schedule for outbox retries (section 5.7).

Exponential backoff with jitter: 5s, 30s, 2m, 10m, 30m, then hourly to a cap.
A 429's ``Retry-After`` header is respected exactly and skips the schedule
and jitter entirely, per the spec ("respect that header exactly").
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

SCHEDULE = [5, 30, 120, 600, 1800]  # 5s, 30s, 2m, 10m, 30m
HOURLY_CAP = 3600

JITTER_FRACTION = 0.2


def backoff_seconds(attempts: int) -> int:
    """Seconds to wait before the next attempt, given attempts made so far."""
    if attempts <= 0:
        return 0
    index = attempts - 1
    base = SCHEDULE[index] if index < len(SCHEDULE) else HOURLY_CAP
    jitter = base * JITTER_FRACTION
    return max(1, int(base + random.uniform(-jitter, jitter)))


def next_attempt_time(
    attempts: int,
    *,
    retry_after: float | None = None,
    now: datetime | None = None,
) -> datetime:
    """When the next attempt should run, respecting Retry-After exactly when given."""
    now = now or datetime.now(timezone.utc)
    delay = retry_after if retry_after is not None else backoff_seconds(attempts)
    return now + timedelta(seconds=delay)
