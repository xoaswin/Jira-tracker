"""Speech-to-text for voice check-ins (Groq Whisper).

The desktop check-in card and the assistant record a short clip and send the
raw bytes here; we forward them to Groq's OpenAI-compatible transcription
endpoint with the user's Groq key (keychain) and return the text. Nothing is
stored. Known Jira project keys go in the prompt so "P P V M one two three"
comes back as "PPVM-123".
"""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Issue
from app.secrets import GROQ_API_KEY, get_secret_store

_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"
MAX_BYTES = 10 * 1024 * 1024  # ~10 minutes of opus; a check-in is seconds
_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _prompt(db: Session) -> str:
    keys = [k for (k,) in db.execute(select(Issue.project_key).distinct()).all() if k]
    base = "Work check-in about Jira tickets"
    return f"{base} such as {', '.join(f'{k}-123' for k in keys[:6])}." if keys else f"{base}."


def transcribe(db: Session, audio: bytes, content_type: str | None) -> str:
    if not audio:
        raise VoiceError("No audio received.", 400)
    if len(audio) > MAX_BYTES:
        raise VoiceError("That recording is too long.", 413)
    key = get_secret_store().get(GROQ_API_KEY)
    if not key:
        raise VoiceError("Voice needs a Groq API key: add one in Settings, AI provider Groq.", 409)
    mime = (content_type or "audio/webm").split(";")[0].strip().lower()
    ext = _EXT.get(mime, "webm")
    try:
        resp = httpx.post(
            _URL,
            headers={"Authorization": f"Bearer {key}"},
            data={"model": MODEL, "response_format": "json", "prompt": _prompt(db), "temperature": "0"},
            files={"file": (f"checkin.{ext}", audio, mime)},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Couldn't reach Groq: {exc.__class__.__name__}.") from exc
    if resp.status_code == 401:
        raise VoiceError("Groq rejected the API key. Update it in Settings.", 409)
    if resp.status_code >= 400:
        raise VoiceError(f"Transcription failed ({resp.status_code}).")
    return ((resp.json() or {}).get("text") or "").strip()
