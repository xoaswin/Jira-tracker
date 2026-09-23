"""Jira datetime formatting and parsing.

The worklog ``started`` field is strictly formatted and is the single most
common source of a 400 response from the Jira API:

    yyyy-MM-dd'T'HH:mm:ss.SSSZ      e.g. 2026-09-07T09:30:00.000+0530

Rules that trip people up:
  * Milliseconds are mandatory, exactly three digits.
  * The timezone offset must have NO colon: ``+0530``, not ``+05:30``.
  * Python's ``strftime("%z")`` gives ``+0530`` correctly, but ``isoformat()``
    gives ``+05:30``. So we build the string manually.
"""

from __future__ import annotations

from datetime import datetime, timezone

from dateutil import parser as _dateutil_parser


def jira_datetime(dt: datetime) -> str:
    """Format a datetime into Jira's exact worklog ``started`` format.

    A naive datetime (no tzinfo) is assumed to be UTC, because sending a naive
    timestamp to Jira without an offset is never what we want.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    millis = dt.microsecond // 1000
    offset = dt.strftime("%z")  # e.g. "+0530", already colon-free
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}" + offset


def parse_jira_datetime(value: str) -> datetime:
    """Parse a Jira timestamp string back into an aware datetime.

    Jira returns timestamps in the same ``+0530`` (colon-free) offset style;
    dateutil handles that plus the ISO ``+05:30`` variant, so this is tolerant
    of both.
    """
    dt = _dateutil_parser.isoparse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
