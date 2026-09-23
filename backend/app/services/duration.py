"""Session duration maths (section 14: duration with pauses and manual override).

Duration pushed to Jira = (ended_at - started_at) - paused_seconds, unless
adjusted_seconds is set, in which case that wins (section 4).
"""

from __future__ import annotations

from datetime import datetime, timezone


def _aware(dt: datetime) -> datetime:
    """Treat any naive datetime as UTC so arithmetic never mixes aware/naive."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def effective_duration_seconds(
    started_at: datetime,
    ended_at: datetime | None,
    paused_seconds: int,
    adjusted_seconds: int | None = None,
) -> int:
    """The duration that will be logged to Jira, in whole seconds.

    A manual override always wins. Otherwise it is wall-clock elapsed minus the
    accumulated pause time, floored at zero (never negative).
    """
    if adjusted_seconds is not None:
        return max(0, int(adjusted_seconds))
    if ended_at is None:
        raise ValueError("ended_at is required when adjusted_seconds is not set")
    gross = (_aware(ended_at) - _aware(started_at)).total_seconds()
    return max(0, int(gross - (paused_seconds or 0)))


def live_elapsed_seconds(
    started_at: datetime,
    now: datetime,
    paused_seconds: int,
    state: str,
    paused_at: datetime | None,
) -> int:
    """Elapsed time for an in-flight session (for the running timer display).

    Includes the current, not-yet-accumulated pause span when the session is
    currently paused.
    """
    gross = (_aware(now) - _aware(started_at)).total_seconds()
    current_pause = 0.0
    if state == "paused" and paused_at is not None:
        current_pause = (_aware(now) - _aware(paused_at)).total_seconds()
    return max(0, int(gross - (paused_seconds or 0) - current_pause))
