"""Tests for session duration maths (section 14)."""

from datetime import datetime, timedelta, timezone

from app.services.duration import effective_duration_seconds, live_elapsed_seconds

UTC = timezone.utc


def _t(minutes=0, seconds=0):
    return datetime(2026, 9, 7, 9, 0, 0, tzinfo=UTC) + timedelta(minutes=minutes, seconds=seconds)


def test_plain_duration_no_pause():
    assert effective_duration_seconds(_t(0), _t(60), 0) == 3600


def test_duration_subtracts_pause():
    assert effective_duration_seconds(_t(0), _t(60), 600) == 3000


def test_adjusted_seconds_wins_over_computed():
    assert effective_duration_seconds(_t(0), _t(60), 600, adjusted_seconds=1800) == 1800


def test_adjusted_seconds_wins_even_without_ended_at():
    assert effective_duration_seconds(_t(0), None, 0, adjusted_seconds=120) == 120


def test_duration_never_negative():
    # Pause longer than elapsed -> clamp to 0.
    assert effective_duration_seconds(_t(0), _t(10), 99999) == 0


def test_adjusted_negative_clamped_to_zero():
    assert effective_duration_seconds(_t(0), _t(60), 0, adjusted_seconds=-50) == 0


def test_live_elapsed_active():
    assert live_elapsed_seconds(_t(0), _t(30), 0, "active", None) == 1800


def test_live_elapsed_active_with_accumulated_pause():
    assert live_elapsed_seconds(_t(0), _t(30), 300, "active", None) == 1500


def test_live_elapsed_while_currently_paused_includes_current_span():
    # started 30m ago, 300s already accumulated, currently paused for 2m more.
    now = _t(30)
    paused_at = _t(28)
    assert live_elapsed_seconds(_t(0), now, 300, "paused", paused_at) == 1500 - 120
