"""Settings routes (Phase 5, section 4/16).

    GET   /api/settings   -> current settings (AI provider, nudge, idle, tempo)
    PATCH /api/settings   -> update settings; third-party AI keys go to keychain

Third-party AI keys (Gemini, Groq) are never returned and never stored in the
DB: they go to the keychain (section 8, rule 4). The response only reports
whether each key is present.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import SettingsOut, SettingsUpdate
from app.secrets import GEMINI_API_KEY, GROQ_API_KEY, get_secret_store
from app.services.connection import ensure_settings_row

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_out(row) -> SettingsOut:
    store = get_secret_store()
    out = SettingsOut.model_validate(row)
    out.has_gemini_key = bool(store.get(GEMINI_API_KEY))
    out.has_groq_key = bool(store.get(GROQ_API_KEY))
    return out


@router.get("", response_model=SettingsOut)
def get_settings_route(db: Session = Depends(get_db)) -> SettingsOut:
    return _to_out(ensure_settings_row(db))


@router.patch("", response_model=SettingsOut)
def update_settings_route(
    payload: SettingsUpdate, db: Session = Depends(get_db)
) -> SettingsOut:
    row = ensure_settings_row(db)

    # Scalar settings fields (exclude the keychain-bound key fields).
    data = payload.model_dump(exclude_unset=True)
    store = get_secret_store()
    if "gemini_api_key" in data:
        key = data.pop("gemini_api_key")
        if key:
            store.set(GEMINI_API_KEY, key)
    if "groq_api_key" in data:
        key = data.pop("groq_api_key")
        if key:
            store.set(GROQ_API_KEY, key)

    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _to_out(row)
