"""The workday follows settings.timezone (IST by default), not UTC/the machine."""

from datetime import date, datetime, timezone

from app.services.tz import day_bounds, is_valid_timezone, local_day, zone


def test_late_utc_evening_is_next_day_in_ist():
    ist = zone("Asia/Kolkata")
    # 20:00 UTC = 01:30 IST the next day.
    assert local_day(datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc), ist) == date(2026, 9, 28)
    # Naive datetimes are treated as UTC (how SQLite hands them back).
    assert local_day(datetime(2026, 9, 27, 20, 0), ist) == date(2026, 9, 28)


def test_ist_day_bounds_are_utc_instants():
    start, end = day_bounds(date(2026, 9, 28), date(2026, 9, 28), zone("Asia/Kolkata"))
    assert start == datetime(2026, 9, 27, 18, 30, tzinfo=timezone.utc)
    assert end.astimezone(timezone.utc).hour == 18 and end.minute == 29


def test_unknown_zone_falls_back_to_ist():
    assert not is_valid_timezone("Mars/Olympus")
    tz = zone("Mars/Olympus")
    assert datetime(2026, 1, 1, tzinfo=timezone.utc).astimezone(tz).utcoffset().total_seconds() == 19800
