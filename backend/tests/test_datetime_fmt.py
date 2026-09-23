"""Tests for jira_datetime (section 14: exact format across timezones + ms padding)."""

from datetime import datetime, timedelta, timezone

from app.jira.datetime_fmt import jira_datetime, parse_jira_datetime

IST = timezone(timedelta(hours=5, minutes=30))  # Asia/Kolkata, half-hour offset
UTC = timezone.utc
PST = timezone(timedelta(hours=-8))


def test_format_ist_half_hour_offset_no_colon():
    dt = datetime(2026, 9, 7, 9, 30, 0, 0, tzinfo=IST)
    assert jira_datetime(dt) == "2026-09-07T09:30:00.000+0530"


def test_format_utc():
    dt = datetime(2026, 9, 7, 9, 30, 0, 123000, tzinfo=UTC)
    assert jira_datetime(dt) == "2026-09-07T09:30:00.123+0000"


def test_format_negative_offset_no_colon():
    dt = datetime(2026, 1, 15, 23, 59, 59, 5000, tzinfo=PST)
    # microsecond 5000 -> 5 ms -> "005"
    assert jira_datetime(dt) == "2026-01-15T23:59:59.005-0800"


def test_milliseconds_are_exactly_three_digits():
    dt = datetime(2026, 9, 7, 0, 0, 0, 7000, tzinfo=UTC)  # 7 ms
    out = jira_datetime(dt)
    # find the .SSS part
    ms_part = out.split(".")[1][:3]
    assert ms_part == "007"


def test_milliseconds_truncate_not_round():
    dt = datetime(2026, 9, 7, 0, 0, 0, 999999, tzinfo=UTC)  # 999.999 ms -> 999
    assert jira_datetime(dt).split(".")[1][:3] == "999"


def test_offset_never_contains_colon():
    for tz in (IST, UTC, PST):
        dt = datetime(2026, 6, 1, 12, 0, 0, tzinfo=tz)
        formatted = jira_datetime(dt)
        offset = formatted[-5:]
        assert ":" not in offset
        assert offset[0] in "+-"


def test_naive_datetime_assumed_utc():
    dt = datetime(2026, 9, 7, 9, 30, 0)
    assert jira_datetime(dt) == "2026-09-07T09:30:00.000+0000"


def test_parse_round_trip_preserves_instant():
    dt = datetime(2026, 9, 7, 9, 30, 0, 123000, tzinfo=IST)
    formatted = jira_datetime(dt)
    parsed = parse_jira_datetime(formatted)
    # Same instant in time (compare as UTC).
    assert parsed.astimezone(UTC) == dt.astimezone(UTC)


def test_parse_tolerates_iso_colon_offset():
    parsed = parse_jira_datetime("2026-09-07T09:30:00.000+05:30")
    assert parsed.astimezone(UTC) == datetime(2026, 9, 7, 4, 0, 0, tzinfo=UTC)
