"""Git context service: resolve configured repo paths to a Start-screen chip.

Repo paths come from the Code folders setting plus the GIT_REPO_PATHS env
default (see ``app.services.repos``).
The heavy lifting lives in ``app.integrations.git``; this thin layer just wires
config in and shapes the result for the API.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.integrations.git import GitContext, detect_current_context
from app.services.repos import repo_paths


def current_git_context(db: Session | None = None) -> GitContext | None:
    """Detect the currently active repo from configured paths, or None."""
    return detect_current_context(repo_paths(db))
