"""Which local git repos to read: the in-app Code folders setting plus the
GIT_REPO_PATHS env default (dev setups). The packaged desktop app has no .env,
so the setting is the real source there."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings


def repo_paths(db: Session | None = None) -> list[str]:
    paths: list[str] = []
    if db is not None:
        from app.services.connection import get_settings_row

        row = get_settings_row(db)
        paths += [p for p in (getattr(row, "git_repo_paths", None) or []) if p]
    for p in get_settings().git_repo_paths:
        if p not in paths:
            paths.append(p)
    return [p.strip() for p in paths if p and p.strip()]
