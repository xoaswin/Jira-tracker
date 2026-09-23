"""Auth routes: connect, status, disconnect (section 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.jira.client import JiraClient, JiraError
from app.schemas import AuthStatus, ConnectRequest
from app.secrets import get_secret_store
from app.services.connection import (
    ensure_settings_row,
    get_settings_row,
    get_token,
    save_connection,
    store_token,
    clear_connection,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_status(db: Session) -> AuthStatus:
    row = get_settings_row(db)
    connected = bool(row and row.jira_base_url and row.jira_email and row.account_id and get_token())
    return AuthStatus(
        connected=connected,
        account_id=row.account_id if row else None,
        display_name=row.display_name if row else None,
        email=row.jira_email if row else None,
        base_url=row.jira_base_url if row else None,
        secret_backend=get_secret_store().kind,
        uses_tempo=row.uses_tempo if row else False,
    )


@router.post("/connect", response_model=AuthStatus)
def connect(payload: ConnectRequest, db: Session = Depends(get_db)) -> AuthStatus:
    """Validate the token against /myself, store it in the keychain, save details."""
    client = JiraClient(payload.base_url, payload.email, payload.token)
    try:
        me = client.myself()
    except JiraError as exc:
        # Surface Jira's real response so the user knows what was wrong (rule 8).
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc
    finally:
        client.close()

    # /myself must return a JSON object with an accountId. If we got HTML or any
    # other shape (a common symptom of a wrong base URL that resolves to Jira's
    # web UI rather than the REST API), fail loudly with guidance rather than
    # crashing on a missing key (rule 8).
    if not isinstance(me, dict) or not me.get("accountId"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Connected to the site but did not get a valid Jira REST "
                "response. Check the base URL is just your site root, e.g. "
                "https://yourcompany.atlassian.net (not a board or project URL)."
            ),
        )

    ensure_settings_row(db)
    store_token(payload.token)
    save_connection(
        db,
        # Persist the normalised root the client actually used, so a pasted
        # board/project URL is cleaned up once and for all.
        base_url=client.base_url,
        email=payload.email,
        account_id=me.get("accountId"),
        display_name=me.get("displayName"),
    )
    return _auth_status(db)


@router.get("/status", response_model=AuthStatus)
def status(db: Session = Depends(get_db)) -> AuthStatus:
    return _auth_status(db)


@router.delete("", status_code=204)
def disconnect(db: Session = Depends(get_db)) -> None:
    clear_connection(db)
