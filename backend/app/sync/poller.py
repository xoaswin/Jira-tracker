"""Background outbox poller (section 4, Phase 2).

A single asyncio task, started in the app lifespan, that wakes every
``POLL_INTERVAL_SECONDS`` and drains any due outbox items. This is what makes
durability real: kill the network mid-push, restart the app, and the worklog
still lands once the network returns, with no user action (acceptance test for
Phase 2).

``process_due_items`` is synchronous (it does blocking DB and HTTP work), so we
run it in a worker thread to keep the event loop responsive. Each pass opens and
closes its own DB session, mirroring the request-scoped session lifecycle.
"""

from __future__ import annotations

import asyncio
import logging

from app.db import SessionLocal
from app.sync.worker import process_due_items

logger = logging.getLogger("jira_tracker.outbox_poller")

POLL_INTERVAL_SECONDS = 15


def _drain_once() -> dict:
    """One synchronous drain pass with its own DB session."""
    db = SessionLocal()
    try:
        return process_due_items(db)
    finally:
        db.close()


async def run_outbox_poller(interval: float = POLL_INTERVAL_SECONDS) -> None:
    """Loop forever, draining due outbox items every ``interval`` seconds.

    Cancelled cleanly on shutdown via the lifespan. Any unexpected error in a
    pass is logged and swallowed so one bad pass never kills the poller.
    """
    logger.info("Outbox poller started (interval=%ss)", interval)
    try:
        while True:
            try:
                result = await asyncio.to_thread(_drain_once)
                if result.get("processed"):
                    logger.info("Outbox poller processed %s item(s)", result["processed"])
            except Exception:  # noqa: BLE001 - never let one pass kill the loop
                logger.exception("Outbox poller pass failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Outbox poller stopped")
        raise
