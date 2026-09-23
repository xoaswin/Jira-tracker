"""Pure unit tests for due-date urgency classification."""

from datetime import date

from app.services.my_tickets import _classify


TODAY = date(2026, 9, 18)


def test_overdue_when_past_and_not_done():
    urgency, days = _classify(date(2026, 9, 10), TODAY, is_done=False)
    assert urgency == "overdue"
    assert days == -8


def test_due_today():
    urgency, days = _classify(TODAY, TODAY, is_done=False)
    assert urgency == "due_today"
    assert days == 0


def test_due_soon_within_window():
    urgency, days = _classify(date(2026, 9, 20), TODAY, is_done=False)
    assert urgency == "due_soon"
    assert days == 2


def test_scheduled_when_far_out():
    urgency, _ = _classify(date(2026, 12, 1), TODAY, is_done=False)
    assert urgency == "scheduled"


def test_no_due_when_missing():
    urgency, days = _classify(None, TODAY, is_done=False)
    assert urgency == "no_due"
    assert days is None


def test_done_ticket_is_never_overdue():
    # A completed ticket with a past due date should not scream for attention.
    urgency, _ = _classify(date(2026, 9, 10), TODAY, is_done=True)
    assert urgency != "overdue"
