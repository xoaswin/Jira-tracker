"""Personal velocity: how long work actually takes you, learned from history.

Joins completed local sessions to their cached issue's type (Story / Bug /
Task / Sub-task) and rolls up the *actual* time spent per type. This is the
foundation for honest day-planning: instead of guessing, we estimate a ticket
from how long tickets of that type have really taken you.

All local and deterministic. No Jira calls. Degrades gracefully: with no
history for a type we fall back to the overall average, and with no history at
all the caller uses a fixed default.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Issue, WorkSession
from app.services.duration import effective_duration_seconds

# Ignore sessions shorter than this when learning velocity: sub-minute blips and
# mis-starts would drag the average down and are not real "how long a ticket
# takes" signal.
_MIN_SAMPLE_SECONDS = 60

# A fixed floor used only when there is no history whatsoever, so a plan never
# estimates zero. One hour is a neutral default per work item.
DEFAULT_ESTIMATE_SECONDS = 3600


@dataclass
class TypeVelocity:
    issue_type: str | None
    sample_count: int
    avg_seconds: int
    median_seconds: int


@dataclass
class Velocity:
    """Learned durations per issue type, plus an overall fallback."""

    by_type: dict[str, TypeVelocity]
    overall_avg_seconds: int
    overall_median_seconds: int
    total_samples: int

    def estimate_seconds(self, issue_type: str | None) -> int:
        """Best estimate for a ticket of ``issue_type``.

        Prefer that type's median (robust to outliers); fall back to the overall
        median; finally the fixed default when there is no history at all.
        """
        if issue_type and issue_type in self.by_type:
            tv = self.by_type[issue_type]
            if tv.sample_count > 0:
                return tv.median_seconds
        if self.total_samples > 0:
            return self.overall_median_seconds
        return DEFAULT_ESTIMATE_SECONDS


def _aggregate(seconds: list[int]) -> tuple[int, int]:
    """(avg, median) as whole seconds; (0, 0) for an empty list."""
    if not seconds:
        return 0, 0
    return int(statistics.mean(seconds)), int(statistics.median(seconds))


def compute_velocity(db: Session) -> Velocity:
    """Learn per-type actual durations from all completed sessions with a ticket.

    Sessions are joined to the cached ``issues`` row by issue_key to recover the
    type. Sessions whose issue is not cached (or has no type) are grouped under
    the overall stats but not attributed to a type.
    """
    # Map issue_key -> issue_type from the cache (one query).
    type_by_key: dict[str, str | None] = dict(
        db.execute(select(Issue.issue_key, Issue.issue_type)).all()
    )

    stmt = select(WorkSession).where(WorkSession.state == "completed")
    per_type: dict[str, list[int]] = {}
    all_seconds: list[int] = []

    for s in db.execute(stmt).scalars().all():
        if not s.issue_key:
            continue
        secs = effective_duration_seconds(
            s.started_at, s.ended_at, s.paused_seconds, s.adjusted_seconds
        )
        if secs < _MIN_SAMPLE_SECONDS:
            continue
        all_seconds.append(secs)
        itype = type_by_key.get(s.issue_key)
        if itype:
            per_type.setdefault(itype, []).append(secs)

    by_type: dict[str, TypeVelocity] = {}
    for itype, seconds in per_type.items():
        avg, median = _aggregate(seconds)
        by_type[itype] = TypeVelocity(
            issue_type=itype,
            sample_count=len(seconds),
            avg_seconds=avg,
            median_seconds=median,
        )

    overall_avg, overall_median = _aggregate(all_seconds)
    return Velocity(
        by_type=by_type,
        overall_avg_seconds=overall_avg,
        overall_median_seconds=overall_median,
        total_samples=len(all_seconds),
    )
