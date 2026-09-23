"""Application configuration via pydantic-settings.

This holds *static* app configuration read from the environment / ``.env``.
The live Jira connection details (base url, email, account id) are the runtime
source of truth in the ``settings`` DB row, written by the auth screen. The env
values here act only as first-run defaults.

The API token is NEVER read from here. It lives in the OS keychain (see
``app.secrets``).
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Repository backend root: .../jira-tracker/backend
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core app ---
    app_port: int = 8756
    database_url: str = f"sqlite:///{BACKEND_ROOT / 'data' / 'tracker.db'}"
    timezone: str = "UTC"

    # --- Secrets ---
    # "auto" tries the OS keyring and falls back to an encrypted-perms file.
    secret_backend: str = "auto"  # auto | keyring | file
    keyring_service: str = "jira-tracker"

    # --- Logging ---
    log_dir: str = str(BACKEND_ROOT / "logs")
    log_level: str = "INFO"

    # --- Outbox worker (Phase 2) ---
    # The background poller drains due outbox items every few seconds. Tests
    # drive the worker explicitly, so it defaults off under pytest (see below).
    disable_background_poller: bool = "pytest" in sys.modules

    # --- First-run Jira defaults (real values live in the DB settings row) ---
    jira_base_url: str | None = None
    jira_email: str | None = None

    # --- AI (used from phase 5; harmless defaults now) ---
    ai_provider: str = "ollama"  # ollama | gemini | groq | none
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    embedding_model: str = "all-MiniLM-L6-v2"

    # --- Git integration (phase 3) ---
    # NoDecode: pydantic-settings v2 would otherwise json.loads() a list-typed
    # env var before our validator runs, so a comma-separated GIT_REPO_PATHS
    # (the documented .env format, section 16) would crash startup. NoDecode
    # hands the raw string to _split_repo_paths below instead.
    git_repo_paths: Annotated[list[str], NoDecode] = []

    # --- Behaviour (phase 5) ---
    idle_threshold_minutes: int = 15
    nudge_time: str = "18:00"

    @field_validator("git_repo_paths", mode="before")
    @classmethod
    def _split_repo_paths(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def data_dir(self) -> Path:
        # Derive the on-disk data dir for sqlite file databases.
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.replace("sqlite:///", "", 1))
            return db_path.parent
        return BACKEND_ROOT / "data"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Ensure runtime directories exist.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    return settings
