"""Plan my day: rank the tickets assigned to me and fit them to my capacity.

Combines three signals the app already has:

* My Tickets (assignee = currentUser()), with due-date urgency,
* Jira priority on each ticket,
* my learned velocity (how long tickets of each type actually take me),

to produce an ordered plan that greedily fills a capacity budget (hours I have
today), marking which tickets fit and which overflow. Read-only and advisory:
it never writes to Jira and never blocks on AI.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.jira.client import JiraClient
from app.services.my_tickets import MyTicket, get_my_tickets
from app.services.velocity import Velocity, compute_velocity

# Urgency ordering (lower = do sooner). Mirrors my_tickets buckets.
_URGENCY_RANK = {
    "overdue": 0,
    "due_today": 1,
    "due_soon": 2,
    "scheduled": 3,
    "no_due": 4,
}

# Jira priority ordering (lower = more important). Unknown priorities sort as
# Medium so an unprioritised ticket is neither pushed to the top nor the bottom.
_PRIORITY_RANK = {
    "highest": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "lowest": 4,
}
_DEFAULT_PRIORITY_RANK = 2


@dataclass
class PlanItem:
    ticket: MyTicket
    estimate_seconds: int
    # True if this ticket fits within the remaining capacity when reached.
    fits: bool
    # Cumulative planned seconds through this item (only counting fitted items).
    cumulative_seconds: int


@dataclass
class DayPlan:
    capacity_seconds: int
    planned_seconds: int  # sum of fitted estimates
    overflow_seconds: int  # sum of estimates that did not fit
    items: list[PlanItem]
    velocity: Velocity

    @property
    def fitted_count(self) -> int:
        return sum(1 for i in self.items if i.fits)


def _priority_rank(priority: str | None) -> int:
    return _PRIORITY_RANK.get((priority or "").strip().lower(), _DEFAULT_PRIORITY_RANK)


def _plan_sort_key(t: MyTicket) -> tuple[int, int, int]:
    """Order: urgency bucket, then priority, then soonest due date."""
    return (
        _URGENCY_RANK.get(t.urgency, 99),
        _priority_rank(t.priority),
        t.days_until_due if t.days_until_due is not None else 10_000,
    )


def build_day_plan(
    db: Session, client: JiraClient, *, capacity_hours: float
) -> DayPlan:
    """Assemble today's plan for a capacity budget (in hours)."""
    capacity_seconds = max(0, int(capacity_hours * 3600))
    velocity = compute_velocity(db)

    tickets = sorted(get_my_tickets(client), key=_plan_sort_key)

    items: list[PlanItem] = []
    used = 0
    overflow = 0
    for t in tickets:
        est = velocity.estimate_seconds(t.issue_type)
        # A ticket fits if adding its estimate stays within capacity. We do not
        # split tickets; a big first ticket can leave smaller ones fitting after
        # it only if there is still room (greedy in priority order).
        if used + est <= capacity_seconds:
            used += est
            fits = True
        else:
            overflow += est
            fits = False
        items.append(
            PlanItem(
                ticket=t,
                estimate_seconds=est,
                fits=fits,
                cumulative_seconds=used,
            )
        )

    return DayPlan(
        capacity_seconds=capacity_seconds,
        planned_seconds=used,
        overflow_seconds=overflow,
        items=items,
        velocity=velocity,
    )
