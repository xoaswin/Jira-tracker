"""Database engine, session factory, and the declarative base.

SQLite via SQLAlchemy 2.x. Foreign keys are enforced with a PRAGMA (SQLite does
not enforce them by default). Sessions are provided to FastAPI routes via the
``get_db`` dependency.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class UTCDateTime(TypeDecorator):
    """A DateTime that stores UTC and always returns tz-aware UTC.

    SQLite does not preserve tzinfo, which otherwise leaves naive datetimes in
    the DB that cannot be compared with tz-aware ``utcnow()``. This decorator
    normalises on the way in (to naive UTC for storage) and re-attaches UTC on
    the way out, so the rest of the app only ever sees aware UTC datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)

_settings = get_settings()

# check_same_thread=False: the outbox worker (phase 2) and request threads share
# the engine. Safe here because we use short-lived Sessions, one per unit of work.
_connect_args = (
    {"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    _settings.database_url,
    connect_args=_connect_args,
    future=True,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    """Enforce foreign keys on every SQLite connection."""
    if _settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def reset_engine_for_tests(database_url: str) -> None:
    """Rebind the global engine/SessionLocal to a fresh database.

    Mirrors ``reset_secret_store_for_tests``: the engine is a process-wide
    singleton bound at import, so multiple app-importing test modules would
    otherwise share one SQLite file (the first import wins). Tests call this in
    their client fixture to get true per-module isolation.

    ``SessionLocal`` is reconfigured in place (not reassigned), so existing
    ``from app.db import SessionLocal`` references stay valid and pick up the new
    bind automatically.
    """
    global engine, _settings, _connect_args

    # Mutate the cached settings object so run_migrations (which reads
    # get_settings().database_url) targets the new database too.
    _settings.database_url = database_url
    _connect_args = (
        {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    )
    engine.dispose()
    engine = create_engine(database_url, connect_args=_connect_args, future=True)
    event.listen(engine, "connect", _enable_sqlite_fk)
    SessionLocal.configure(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a DB session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
