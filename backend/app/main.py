"""FastAPI application entrypoint.

Runs migrations and configures logging on startup, wires the routers, maps our
domain errors to clean HTTP responses (loud, with Jira's real body), and in
production serves the built frontend as static files from a single process.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BACKEND_ROOT, get_settings
from app.db import SessionLocal
from app.db_init import run_migrations
from app.jira.client import JiraError, configure_jira_logging
from app.routers import (
    auth,
    boards,
    insights as insights_router,
    issues,
    manage,
    match,
    my_tickets,
    outbox,
    reports,
    sessions,
    settings as settings_router,
    velocity as velocity_router,
)
from app.services.connection import NotConnectedError, ensure_settings_row
from app.sync.poller import run_outbox_poller

logger = logging.getLogger("jira_tracker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    configure_jira_logging(settings.log_dir, settings.log_level)
    run_migrations()
    # Make sure the singleton settings row exists.
    db = SessionLocal()
    try:
        ensure_settings_row(db)
    finally:
        db.close()
    logger.info("jira-tracker backend ready on port %s", settings.app_port)

    # Start the background outbox poller (Phase 2 durability). Disabled under
    # pytest, where tests drive the worker explicitly and a background loop would
    # race the assertions / touch the mocked network unpredictably.
    poller_task: asyncio.Task | None = None
    if not settings.disable_background_poller:
        poller_task = asyncio.create_task(run_outbox_poller())
        # Phase 3: if the embedding model changed (or embeddings were never
        # computed), rebuild them in the background so startup stays fast and the
        # model download never blocks the first request (section 6).
        asyncio.create_task(asyncio.to_thread(_rebuild_embeddings_safely))

    try:
        yield
    finally:
        if poller_task is not None:
            poller_task.cancel()
            try:
                await poller_task
            except asyncio.CancelledError:
                pass


def _rebuild_embeddings_safely() -> None:
    """Background startup task: recompute stale embeddings, never raising.

    Runs in a worker thread. If the embedding model is unavailable this is a
    cheap no-op, so it is safe to fire unconditionally on every startup.
    """
    from app.services.matching import rebuild_all_embeddings

    db = SessionLocal()
    try:
        count = rebuild_all_embeddings(db)
        if count:
            logger.info("Rebuilt %d issue embeddings on startup", count)
    except Exception:  # never let a background task kill anything
        logger.exception("Background embedding rebuild failed")
    finally:
        db.close()


app = FastAPI(title="Jira Work Session Tracker", version="0.1.0", lifespan=lifespan)

# Vite dev server proxies /api, so CORS is not strictly needed, but allow the
# local dev origins to keep direct calls painless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NotConnectedError)
async def _not_connected_handler(request: Request, exc: NotConnectedError):
    return JSONResponse(status_code=409, content={"detail": str(exc), "code": "not_connected"})


@app.exception_handler(JiraError)
async def _jira_error_handler(request: Request, exc: JiraError):
    # 401 -> reauthenticate signal; otherwise 502 (upstream failure). Body is
    # always Jira's real response so the UI can show what field was wrong.
    status = 401 if exc.status_code == 401 else 502
    return JSONResponse(
        status_code=status,
        content={"detail": exc.to_dict(), "code": "jira_error"},
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(boards.router)
app.include_router(sessions.router)
app.include_router(outbox.router)
app.include_router(match.router)
app.include_router(issues.router)
app.include_router(reports.router)
app.include_router(settings_router.router)
app.include_router(manage.router)
app.include_router(my_tickets.router)
app.include_router(velocity_router.router)
app.include_router(insights_router.router)


# --- Production static serving (single process on 8756) ---
_frontend_dist = BACKEND_ROOT.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
    logger.info("Serving built frontend from %s", _frontend_dist)


def _print_routes() -> None:  # small dev helper
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods:
            print(sorted(methods), route.path)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=get_settings().app_port, reload=True)
