"""Velocity learning tests: per-type actual durations from completed sessions."""

import os
import tempfile
from datetime import timedelta

_TMP = tempfile.mkdtemp(prefix="jt-vel-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import pytest  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.models import Issue, WorkSession, utcnow  # noqa: E402
from app.services.velocity import (  # noqa: E402
    DEFAULT_ESTIMATE_SECONDS,
    compute_velocity,
)


@pytest.fixture
def db():
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    from app.db_init import run_migrations

    run_migrations()
    s = SessionLocal()
    # Start each test from an empty slate: this module reuses one SQLite file, so
    # rows from a prior test would otherwise leak in (unique issue_key collisions
    # and skewed velocity stats).
    s.query(WorkSession).delete()
    s.query(Issue).delete()
    s.commit()
    yield s
    s.close()


def _completed(db, issue_key, seconds):
    start = utcnow() - timedelta(seconds=seconds + 10)
    db.add(
        WorkSession(
            description="w",
            issue_key=issue_key,
            started_at=start,
            ended_at=start + timedelta(seconds=seconds),
            paused_seconds=0,
            state="completed",
        )
    )


def test_no_history_uses_default_estimate(db):
    vel = compute_velocity(db)
    assert vel.total_samples == 0
    assert vel.estimate_seconds("Bug") == DEFAULT_ESTIMATE_SECONDS


def test_per_type_median_learned(db):
    db.add(Issue(jira_id="1", issue_key="PAY-1", issue_type="Bug"))
    db.add(Issue(jira_id="2", issue_key="PAY-2", issue_type="Bug"))
    db.add(Issue(jira_id="3", issue_key="PAY-3", issue_type="Story"))
    # Bugs: 1h and 3h -> median 2h. Story: 5h.
    _completed(db, "PAY-1", 3600)
    _completed(db, "PAY-2", 3 * 3600)
    _completed(db, "PAY-3", 5 * 3600)
    db.commit()

    vel = compute_velocity(db)
    assert vel.by_type["Bug"].sample_count == 2
    assert vel.estimate_seconds("Bug") == 2 * 3600  # median of 1h, 3h
    assert vel.estimate_seconds("Story") == 5 * 3600


def test_unknown_type_falls_back_to_overall_median(db):
    db.add(Issue(jira_id="1", issue_key="PAY-1", issue_type="Task"))
    _completed(db, "PAY-1", 2 * 3600)
    db.commit()

    vel = compute_velocity(db)
    # "Epic" has no samples -> overall median (only one sample: 2h).
    assert vel.estimate_seconds("Epic") == 2 * 3600


def test_short_sessions_are_ignored(db):
    db.add(Issue(jira_id="1", issue_key="PAY-1", issue_type="Bug"))
    _completed(db, "PAY-1", 30)  # under the 60s floor
    db.commit()

    vel = compute_velocity(db)
    assert vel.total_samples == 0
    assert "Bug" not in vel.by_type
