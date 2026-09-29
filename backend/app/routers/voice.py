"""POST /api/voice/transcribe: raw audio body (audio/webm etc.) -> {"text"}.

A raw body (not multipart) keeps python-multipart out of the build; the
desktop IPC bridge and the browser both send the recorded Blob as-is.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.voice import VoiceError, transcribe

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe_route(request: Request, db: Session = Depends(get_db)) -> dict:
    audio = await request.body()
    try:
        text = transcribe(db, audio, request.headers.get("content-type"))
    except VoiceError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"text": text}
