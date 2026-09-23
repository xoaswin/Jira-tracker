"""Git context service: resolve configured repo paths to a Start-screen chip.

Repo paths come from ``settings.git_repo_paths`` (env / .env), per section 16.
The heavy lifting lives in ``app.integrations.git``; this thin layer just wires
config in and shapes the result for the API.
"""

from __future__ import annotations

from app.config import get_settings
from app.integrations.git import GitContext, detect_current_context


def current_git_context() -> GitContext | None:
    """Detect the currently active repo from configured paths, or None."""
    settings = get_settings()
    return detect_current_context(settings.git_repo_paths)
