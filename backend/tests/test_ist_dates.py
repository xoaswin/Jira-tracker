"""Ticket dates follow the app timezone (IST), not the laptop (ET) or UTC.

The reported bug: at 06:45 IST (= 21:15 ET the previous evening) the actual
start/end and hand-entered datetimes landed in Jira as ET/UTC wall time.
"""

from datetime import datetime, timezone

from app.jira.editmeta import EditableField, _format_value, display_value
from app.services.auto_dates import _in_zone
from app.services.tz import zone

IST = zone("Asia/Kolkata")
DATETIME = EditableField(field_id="customfield_1", name="Actual start", schema_type="datetime")
DATE = EditableField(field_id="customfield_2", name="Actual end", schema_type="date")

# 06:45 IST on the 29th == 01:15 UTC on the 29th == 21:15 EDT on the 28th.
SESSION_UTC = datetime(2026, 9, 29, 1, 15, tzinfo=timezone.utc)


def test_typed_datetime_is_ist_wall_time():
    # <input datetime-local> sends no offset; it means 06:45 IST.
    assert _format_value(DATETIME, "2026-09-29T06:45", IST) == "2026-09-29T06:45:00.000+0530"


def test_auto_stamped_session_is_written_in_ist():
    stamped = _in_zone(SESSION_UTC, IST).isoformat()
    assert _format_value(DATETIME, stamped, IST) == "2026-09-29T06:45:00.000+0530"
    # A date-only field gets the IST day (the 29th), not the UTC/ET day.
    assert _format_value(DATE, stamped, IST) == "2026-09-29"
    et_evening = "2026-09-28T21:15:00-04:00"  # same instant, ET offset
    assert _format_value(DATE, et_evening, IST) == "2026-09-29"


def test_naive_stored_datetime_is_treated_as_utc():
    naive = SESSION_UTC.replace(tzinfo=None)  # how SQLite returns it
    assert _in_zone(naive, IST).strftime("%Y-%m-%d %H:%M") == "2026-09-29 06:45"


def test_jira_value_in_et_profile_zone_is_shown_as_ist():
    # Jira returns datetimes in the Jira profile's zone (here ET).
    assert display_value(DATETIME, "2026-09-28T21:15:00.000-0400", IST) == "2026-09-29T06:45"
    # Date fields and empty values pass through untouched.
    assert display_value(DATE, "2026-09-29", IST) == "2026-09-29"
    assert display_value(DATETIME, None, IST) is None


def test_without_tz_keeps_previous_behaviour():
    assert _format_value(DATETIME, "2026-09-29T06:45", None) == "2026-09-29T06:45:00.000+0000"
    assert _format_value(DATE, "2026-09-29T06:45:00+05:30", None) == "2026-09-29"
