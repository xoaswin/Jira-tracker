"""Programmatic migration runner so the app self-heals its schema on startup."""

from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config

from app.config import BACKEND_ROOT, get_settings

logger = logging.getLogger("jira_tracker.db_init")


def run_migrations() -> None:
    """Upgrade the database to the latest Alembic revision (idempotent)."""
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    logger.info("Applying database migrations to head...")
    command.upgrade(cfg, "head")
