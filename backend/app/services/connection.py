"""Jira connection state: the settings row + the token in the keychain.

This is the single place that assembles an authenticated :class:`JiraClient`
from persisted connection details. Routes call :func:`build_client`; if the app
is not connected they get a clear :class:`NotConnectedError` (surfaced as 409).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.jira.client import JiraClient
from app.models import AppSettings
from app.secrets import JIRA_TOKEN_KEY, get_secret_store


class NotConnectedError(Exception):
    """Raised when a Jira call is attempted before the app is connected."""


def get_settings_row(db: Session) -> AppSettings | None:
    return db.execute(select(AppSettings).where(AppSettings.id == 1)).scalar_one_or_none()


def ensure_settings_row(db: Session) -> AppSettings:
    """Return the singleton settings row, creating it with app defaults if absent."""
    row = get_settings_row(db)
    if row is None:
        cfg = get_settings()
        row = AppSettings(
            id=1,
            ai_provider=cfg.ai_provider,
            ollama_url=cfg.ollama_url,
            ollama_model=cfg.ollama_model,
            embedding_model=cfg.embedding_model,
            nudge_time=cfg.nudge_time,
            idle_threshold_minutes=cfg.idle_threshold_minutes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


# --- token storage (keychain only) ---

def store_token(token: str) -> None:
    get_secret_store().set(JIRA_TOKEN_KEY, token)


def get_token() -> str | None:
    return get_secret_store().get(JIRA_TOKEN_KEY)


def delete_token() -> None:
    get_secret_store().delete(JIRA_TOKEN_KEY)


# --- connection lifecycle ---

def is_connected(db: Session) -> bool:
    row = get_settings_row(db)
    return bool(
        row
        and row.jira_base_url
        and row.jira_email
        and row.account_id
        and get_token()
    )


def save_connection(
    db: Session, *, base_url: str, email: str, account_id: str, display_name: str | None
) -> AppSettings:
    row = ensure_settings_row(db)
    row.jira_base_url = base_url.rstrip("/")
    row.jira_email = email
    row.account_id = account_id
    row.display_name = display_name
    row.needs_reauth = False
    db.commit()
    db.refresh(row)
    return row


def clear_connection(db: Session) -> None:
    delete_token()
    row = get_settings_row(db)
    if row:
        row.jira_base_url = None
        row.jira_email = None
        row.account_id = None
        row.display_name = None
        db.commit()


def build_client(db: Session) -> JiraClient:
    """Assemble an authenticated client, or raise NotConnectedError."""
    row = get_settings_row(db)
    token = get_token()
    if not (row and row.jira_base_url and row.jira_email and token):
        raise NotConnectedError("Jira is not connected. Connect on the auth screen first.")
    return JiraClient(row.jira_base_url, row.jira_email, token)
