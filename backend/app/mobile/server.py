"""The phone-facing app and its LAN listener.

A separate FastAPI app (not routers on the main app) so the network-exposed
surface is exactly what is declared here: the static phone page plus a few
token-guarded timer routes. It reuses the same session handlers as the laptop
UI, so a stop from the phone pushes the worklog through the same outbox path.

The listener runs in a daemon thread with its own uvicorn loop (uvicorn skips
signal handling off the main thread, so it can't interfere with the main
server's shutdown). It starts when the first device is paired, or at startup
if devices exist, and stops when the last one is revoked.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import db as app_db
from app.config import get_settings
from app.db import get_db
from app.mobile.pairing import active_devices, authenticate
from app.models import AppSettings, Issue, MobileDevice, WorkSession
from app.schemas import SessionComplete, SessionCreate
from app.services.wrapup import today_wrapup

logger = logging.getLogger("jira_tracker.mobile")

STATIC = Path(__file__).parent / "static"
ACTIVE_STATES = ("active", "paused")

mobile_app = FastAPI(title="Jira Tracker mobile", docs_url=None, redoc_url=None, openapi_url=None)


@mobile_app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


def require_device(request: Request, db: Session = Depends(get_db)) -> MobileDevice:
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    device = authenticate(db, token, request.headers.get("user-agent"))
    if device is None:
        raise HTTPException(status_code=401, detail="Not paired. Scan the QR code on your laptop again.")
    return device


# --- static phone app -------------------------------------------------------

@mobile_app.get("/", include_in_schema=False)
def _root() -> RedirectResponse:
    return RedirectResponse("/m/")


@mobile_app.get("/m/", include_in_schema=False)
def _page() -> FileResponse:
    return FileResponse(STATIC / "index.html", media_type="text/html")


@mobile_app.get("/m/manifest.webmanifest", include_in_schema=False)
def _manifest() -> FileResponse:
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@mobile_app.get("/m/icon-256.png", include_in_schema=False)
def _icon() -> FileResponse:
    return FileResponse(STATIC / "icon-256.png", media_type="image/png")


# --- timer API ----------------------------------------------------------------

class StartRequest(BaseModel):
    issue_key: str | None = None
    description: str | None = None


def _active(db: Session) -> WorkSession | None:
    return (
        db.execute(
            select(WorkSession)
            .where(WorkSession.state.in_(ACTIVE_STATES))
            .order_by(WorkSession.started_at.desc())
        )
        .scalars()
        .first()
    )


def _state(db: Session) -> dict:
    from app.routers.sessions import _to_out

    active = _active(db)
    day = today_wrapup(db)
    settings = db.get(AppSettings, 1)
    return {
        # Clock times on the phone follow the app timezone (IST), like the laptop.
        "tz": (settings.timezone if settings else None) or "Asia/Kolkata",
        "session": _to_out(active).model_dump(mode="json") if active else None,
        "today": {
            "date": day.date,
            "tracked_seconds": day.tracked_seconds,
            "logged_seconds": day.logged_seconds,
            "target_seconds": day.target_seconds,
            "sessions": [
                {
                    "id": s.id,
                    "issue_key": s.issue_key,
                    "description": s.description,
                    "seconds": s.seconds,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "sync_state": s.sync_state,
                }
                for s in day.sessions
            ],
        },
    }


@mobile_app.get("/api/m/state")
def state(device: MobileDevice = Depends(require_device), db: Session = Depends(get_db)) -> dict:
    return _state(db)


def _finish_active(db: Session) -> str | None:
    """Complete the running session (pushing its worklog). Returns a warning."""
    from app.routers.sessions import complete_session

    active = _active(db)
    if active is None:
        return None
    result = complete_session(active.id, SessionComplete(), db)
    return result.warning


@mobile_app.post("/api/m/start")
def start(
    req: StartRequest,
    device: MobileDevice = Depends(require_device),
    db: Session = Depends(get_db),
) -> dict:
    """Start tracking; if something is already running, finish it first (switch)."""
    from app.routers.sessions import create_session

    key = (req.issue_key or "").strip().upper() or None
    description = (req.description or "").strip()
    if not description and key:
        issue = db.execute(select(Issue).where(Issue.issue_key == key)).scalar_one_or_none()
        description = issue.summary if issue and issue.summary else key
    if not description:
        raise HTTPException(status_code=422, detail="Pick a ticket or say what you're working on.")

    warning = _finish_active(db)
    out = create_session(SessionCreate(description=description), db)
    if key:
        s = db.get(WorkSession, out.id)
        s.issue_key = key
        s.issue_origin = "manual"
        db.commit()
    return {**_state(db), "warning": warning}


@mobile_app.post("/api/m/pause")
def pause(device: MobileDevice = Depends(require_device), db: Session = Depends(get_db)) -> dict:
    from app.routers.sessions import pause_session

    active = _active(db)
    if active is not None:
        pause_session(active.id, db)
    return _state(db)


@mobile_app.post("/api/m/resume")
def resume(device: MobileDevice = Depends(require_device), db: Session = Depends(get_db)) -> dict:
    from app.routers.sessions import resume_session

    active = _active(db)
    if active is not None:
        resume_session(active.id, db)
    return _state(db)


@mobile_app.post("/api/m/stop")
def stop(device: MobileDevice = Depends(require_device), db: Session = Depends(get_db)) -> dict:
    warning = _finish_active(db)
    return {**_state(db), "warning": warning}


@mobile_app.get("/api/m/tickets")
def tickets(
    q: str = "",
    device: MobileDevice = Depends(require_device),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Tickets to pick from: a search over the local issue cache, or (no query)
    recently tracked keys followed by open tickets assigned to me."""
    q = q.strip()
    stmt = select(Issue).where(or_(Issue.status_category.is_(None), Issue.status_category != "Done"))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Issue.issue_key.ilike(like), Issue.summary.ilike(like)))
        rows = db.execute(stmt.order_by(Issue.updated_at.desc().nullslast()).limit(25)).scalars().all()
        return [_ticket(i) for i in rows]

    recent_keys: list[str] = []
    for (key,) in db.execute(
        select(WorkSession.issue_key)
        .where(WorkSession.issue_key.is_not(None))
        .order_by(WorkSession.started_at.desc())
        .limit(50)
    ).all():
        if key not in recent_keys:
            recent_keys.append(key)
    recent_keys = recent_keys[:6]
    by_key = {
        i.issue_key: i
        for i in db.execute(select(Issue).where(Issue.issue_key.in_(recent_keys))).scalars().all()
    }
    out = [
        _ticket(by_key[k]) if k in by_key else {"issue_key": k, "summary": "", "status": None}
        for k in recent_keys
    ]
    settings = db.get(AppSettings, 1)
    if settings and settings.account_id:
        mine = db.execute(
            stmt.where(Issue.assignee_account_id == settings.account_id)
            .order_by(Issue.updated_at.desc().nullslast())
            .limit(15)
        ).scalars().all()
        out += [_ticket(i) for i in mine if i.issue_key not in recent_keys]
    return out


def _ticket(i: Issue) -> dict:
    return {"issue_key": i.issue_key, "summary": i.summary, "status": i.status}


@mobile_app.get("/api/m/ping")
def ping() -> Response:
    return Response(status_code=204)


# --- listener lifecycle ------------------------------------------------------

_server = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def start_listener() -> bool:
    """Start the LAN listener if it isn't running. Returns True if running."""
    global _server, _thread
    import uvicorn

    with _lock:
        if is_running():
            return True
        cfg = get_settings()
        if cfg.disable_mobile_listener:
            return False
        config = uvicorn.Config(
            mobile_app,
            host="0.0.0.0",  # noqa: S104 - LAN access is the point; every route is token-guarded
            port=cfg.mobile_port,
            log_level="warning",
            lifespan="off",
            access_log=False,
        )
        _server = uvicorn.Server(config)
        _thread = threading.Thread(target=_server.run, name="mobile-listener", daemon=True)
        _thread.start()
        logger.info("mobile companion listening on 0.0.0.0:%s", cfg.mobile_port)
        return True


def stop_listener() -> None:
    global _server, _thread
    with _lock:
        if _server is not None:
            _server.should_exit = True
        if _thread is not None:
            _thread.join(timeout=5)
        _server = None
        _thread = None
        logger.info("mobile companion stopped")


def start_if_paired() -> None:
    """Startup hook: resume listening when devices were paired earlier."""
    db = app_db.SessionLocal()
    try:
        if active_devices(db):
            start_listener()
    except Exception:  # noqa: BLE001 - the phone feature must never break startup
        logger.exception("could not start the mobile companion")
    finally:
        db.close()
