"""Foreground-activity recording, ticket inference, zero-click tracking and
away-pausing (desktop only).

The Electron shell samples the foreground window every few seconds and posts
closed segments here. This module:

* stores/merges them (``ingest``), inferring a Jira key per segment from the
  window title (validated against known project keys, so "UTF-8" is not a
  ticket) or, for editors, from the git branch of the matching Code folder;
* decides whether the timer should start/switch on its own (``suggest``):
  one ticket must dominate the last few minutes of active time;
* applies that with an undo handle (``autotrack`` / ``undo_autotrack``);
* pauses the running timer while you're away (idle/locked) and resumes it on
  return (``set_away``).

Everything stays in the local DB; nothing here talks to Jira directly.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PureWindowsPath

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations.git import current_branch
from app.models import ActivitySegment, AppSettings, Board, Issue, WorkSession, utcnow
from app.services.repos import repo_paths

logger = logging.getLogger("jira_tracker.activity")

RETENTION_DAYS = 45
MERGE_GAP = timedelta(seconds=20)
# Zero-click tracking: the window of recent activity considered, and the share
# of active time one ticket needs within it.
DWELL = timedelta(minutes=5)
DOMINANCE = 0.8
# Don't auto-switch away from a session younger than this (avoids thrash).
MIN_SESSION_AGE = timedelta(minutes=5)
UNDO_SUPPRESS = timedelta(minutes=30)

_KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9})-(\d{1,6})(?![A-Za-z0-9])")

# Process names (lowercased, no .exe) -> category, for the timeline colours and
# the focus radar.
_CATEGORIES = {
    "code": {"code", "code - insiders", "cursor", "windsurf", "devenv", "idea64", "pycharm64",
             "webstorm64", "rider64", "datagrip64", "sublime_text", "notepad++",
             "windowsterminal", "wt", "powershell", "pwsh", "cmd", "wsl", "mintty",
             "postman", "dbeaver", "ssms", "azuredatastudio", "docker desktop"},
    "browser": {"chrome", "msedge", "firefox", "brave", "opera", "arc", "vivaldi"},
    "meeting": {"ms-teams", "teams", "zoom", "webex", "ciscowebexstart", "slack huddle"},
    "chat": {"slack", "discord", "whatsapp", "telegram", "outlook", "olk", "thunderbird"},
    "docs": {"winword", "excel", "powerpnt", "onenote", "notion", "obsidian", "acrord32",
             "acrobat"},
}
_EDITORS = {"code", "code - insiders", "cursor", "windsurf", "idea64", "pycharm64",
            "webstorm64", "rider64", "devenv", "sublime_text"}


def category(app: str) -> str:
    name = (app or "").lower().removesuffix(".exe")
    for cat, names in _CATEGORIES.items():
        if name in names:
            return cat
    return "other"


# --- ticket inference ---------------------------------------------------------

_cache_lock = threading.Lock()
_projects_cache: tuple[float, set[str]] = (0.0, set())
_branch_cache: dict[str, tuple[float, str | None]] = {}


def known_projects(db: Session) -> set[str]:
    """Project keys we know are real (cached 5 min)."""
    global _projects_cache
    with _cache_lock:
        at, keys = _projects_cache
        if time.monotonic() - at < 300 and keys:
            return keys
    found: set[str] = set()
    for (k,) in db.execute(select(Issue.project_key).distinct()).all():
        if k:
            found.add(k.upper())
    for (k,) in db.execute(select(Board.project_key).distinct()).all():
        if k:
            found.add(k.upper())
    for (key,) in db.execute(
        select(WorkSession.issue_key).where(WorkSession.issue_key.is_not(None)).distinct()
    ).all():
        found.add(key.rsplit("-", 1)[0].upper())
    with _cache_lock:
        _projects_cache = (time.monotonic(), found)
    return found


def key_in_text(text: str, projects: set[str]) -> str | None:
    for m in _KEY_RE.finditer(text or ""):
        proj = m.group(1).upper()
        if proj in projects:
            return f"{proj}-{int(m.group(2))}"
    return None


def _branch(path: str) -> str | None:
    now = time.monotonic()
    with _cache_lock:
        hit = _branch_cache.get(path)
        if hit and now - hit[0] < 60:
            return hit[1]
    branch = current_branch(path)
    with _cache_lock:
        _branch_cache[path] = (now, branch)
    return branch


def _repo_name(path: str) -> str:
    return PureWindowsPath(path.replace("/", "\\").rstrip("\\")).name.lower()


def _title_tokens(title: str) -> set[str]:
    # "file.py - my-repo [WSL: Ubuntu] - Visual Studio Code" -> {"file.py", "my-repo", ...}
    cleaned = re.sub(r"\[[^\]]*\]", " ", title or "")
    parts = re.split(r"\s+[-—–]\s+", cleaned)
    return {p.strip().lower() for p in parts if p.strip()}


def infer_key(db: Session, app: str, title: str) -> tuple[str | None, str | None]:
    """(issue_key, source) for a foreground window, or (None, None)."""
    projects = known_projects(db)
    key = key_in_text(title, projects)
    if key:
        return key, "title"
    if (app or "").lower().removesuffix(".exe") in _EDITORS:
        tokens = _title_tokens(title)
        for path in repo_paths(db):
            if _repo_name(path) in tokens:
                branch = _branch(path)
                key = key_in_text(branch or "", projects)
                if key:
                    return key, "branch"
    return None, None


# --- ingest -------------------------------------------------------------------

@dataclass
class SegmentIn:
    start: datetime
    end: datetime
    app: str
    title: str
    kind: str = "active"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ingest(db: Session, segments: list[SegmentIn]) -> int:
    """Store segments, extending the previous row when it's the same window."""
    stored = 0
    last = db.execute(
        select(ActivitySegment).order_by(ActivitySegment.ended_at.desc()).limit(1)
    ).scalar_one_or_none()
    for seg in sorted(segments, key=lambda s: s.start):
        start, end = _aware(seg.start), _aware(seg.end)
        if end <= start:
            continue
        kind = seg.kind if seg.kind in ("active", "idle", "locked") else "active"
        app = (seg.app or "")[:120]
        title = (seg.title or "")[:500]
        if (
            last is not None
            and last.app == app
            and last.title == title
            and last.kind == kind
            and timedelta(0) <= start - _aware(last.ended_at) <= MERGE_GAP
        ):
            last.ended_at = max(_aware(last.ended_at), end)
            continue
        key, source = infer_key(db, app, title) if kind == "active" else (None, None)
        last = ActivitySegment(
            started_at=start, ended_at=end, app=app, title=title, kind=kind,
            issue_key=key, key_source=source,
        )
        db.add(last)
        stored += 1
    db.execute(
        delete(ActivitySegment).where(
            ActivitySegment.ended_at < utcnow() - timedelta(days=RETENTION_DAYS)
        )
    )
    db.commit()
    return stored


# --- zero-click tracking ------------------------------------------------------

_suppressed: dict[str, datetime] = {}  # issue_key -> until (after an undo)


def _active_session(db: Session) -> WorkSession | None:
    return (
        db.execute(
            select(WorkSession)
            .where(WorkSession.state.in_(("active", "paused")))
            .order_by(WorkSession.started_at.desc())
        )
        .scalars()
        .first()
    )


def _in_work_window(settings: AppSettings | None, now: datetime) -> bool:
    if settings is None or not settings.work_start_time or not settings.work_end_time:
        return True
    local = now.astimezone(app_tz_from(settings))
    cur = local.hour * 60 + local.minute

    def hm(v: str) -> int:
        h, m = v.split(":")
        return int(h) * 60 + int(m)

    try:
        s, e = hm(settings.work_start_time), hm(settings.work_end_time)
    except ValueError:
        return True
    return s <= cur < e if s <= e else (cur >= s or cur < e)


def app_tz_from(settings: AppSettings):
    from app.services.tz import zone

    return zone(settings.timezone)


def dominant_key(db: Session, now: datetime) -> tuple[str | None, float]:
    """The ticket owning >= DOMINANCE of active time in the last DWELL, with its
    share, requiring the window to be mostly covered by active activity."""
    since = now - DWELL
    rows = db.execute(
        select(ActivitySegment).where(ActivitySegment.ended_at > since)
    ).scalars().all()
    per_key: dict[str | None, float] = {}
    active_total = 0.0
    for r in rows:
        if r.kind != "active":
            continue
        a = max(_aware(r.started_at), since)
        b = min(_aware(r.ended_at), now)
        secs = (b - a).total_seconds()
        if secs <= 0:
            continue
        active_total += secs
        per_key[r.issue_key] = per_key.get(r.issue_key, 0.0) + secs
    # Need most of the window observed as active, not a 10s glimpse.
    if active_total < DWELL.total_seconds() * DOMINANCE:
        return None, 0.0
    best = max(((k, v) for k, v in per_key.items() if k), key=lambda kv: kv[1], default=None)
    if best is None:
        return None, 0.0
    share = best[1] / active_total
    return (best[0], share) if share >= DOMINANCE else (None, share)


def suggest(db: Session, now: datetime | None = None) -> dict | None:
    """What zero-click tracking would do right now: start/switch, or None."""
    now = now or utcnow()
    settings = db.get(AppSettings, 1)
    if settings is None or not settings.auto_track:
        return None
    if not _in_work_window(settings, now):
        return None
    key, share = dominant_key(db, now)
    if key is None:
        return None
    until = _suppressed.get(key)
    if until and now < until:
        return None
    current = _active_session(db)
    if current is None:
        return {"action": "start", "issue_key": key, "share": round(share, 2)}
    if current.state != "active" or current.issue_key == key:
        return None
    if now - _aware(current.started_at) < MIN_SESSION_AGE:
        return None
    return {
        "action": "switch",
        "issue_key": key,
        "share": round(share, 2),
        "from_issue_key": current.issue_key,
    }


def autotrack(db: Session, issue_key: str) -> dict:
    """Start (or switch to) ``issue_key`` as an auto session. Returns what
    happened, including the finished previous session for the undo toast."""
    from app.routers.sessions import complete_session, create_session
    from app.schemas import SessionComplete, SessionCreate

    key = issue_key.strip().upper()
    previous = None
    current = _active_session(db)
    if current is not None:
        if current.issue_key == key:
            return {"session_id": current.id, "issue_key": key, "previous": None, "changed": False}
        result = complete_session(current.id, SessionComplete(), db)
        previous = {
            "id": current.id,
            "issue_key": current.issue_key,
            "seconds": result.duration_seconds,
            "warning": result.warning,
        }
    issue = db.execute(select(Issue).where(Issue.issue_key == key)).scalar_one_or_none()
    out = create_session(SessionCreate(description=(issue.summary if issue else "") or key), db)
    s = db.get(WorkSession, out.id)
    s.issue_key = key
    s.issue_origin = "auto"
    db.commit()
    return {"session_id": s.id, "issue_key": key, "previous": previous, "changed": True}


def undo_autotrack(db: Session, session_id: int) -> dict:
    """Discard an auto-started session and stop auto-tracking that ticket for a
    while (so it doesn't immediately restart)."""
    s = db.get(WorkSession, session_id)
    if s is None or s.issue_origin != "auto":
        return {"ok": False, "message": "Nothing to undo."}
    if s.state in ("active", "paused"):
        s.state = "abandoned"
        s.ended_at = utcnow()
        db.commit()
    if s.issue_key:
        _suppressed[s.issue_key] = utcnow() + UNDO_SUPPRESS
    return {"ok": True, "message": f"Stopped auto-tracking {s.issue_key or 'that'} for 30 minutes."}


# --- away (idle / locked) -----------------------------------------------------

_paused_by_away: set[int] = set()


def set_away(db: Session, away: bool) -> dict:
    """Pause the running timer while away; resume it on return if we paused it."""
    from app.routers.sessions import pause_session, resume_session

    current = _active_session(db)
    if away:
        if current is not None and current.state == "active":
            pause_session(current.id, db)
            _paused_by_away.add(current.id)
            return {"paused": current.id}
        return {"paused": None}
    resumed = None
    if current is not None and current.id in _paused_by_away and current.state == "paused":
        resume_session(current.id, db)
        resumed = current.id
    _paused_by_away.clear()
    return {"resumed": resumed}


def reset_state_for_tests() -> None:
    global _projects_cache
    _suppressed.clear()
    _paused_by_away.clear()
    _branch_cache.clear()
    _projects_cache = (0.0, set())
