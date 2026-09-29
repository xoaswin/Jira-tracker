"""Voice transcription proxy: key handling, forwarding, and error mapping."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-voice-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Issue  # noqa: E402
from app.secrets import (  # noqa: E402
    GROQ_API_KEY,
    FileBackend,
    get_secret_store,
    reset_secret_store_for_tests,
)

URL = "https://api.groq.com/openai/v1/audio/transcriptions"


@pytest.fixture(scope="module")
def client():
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    reset_secret_store_for_tests(FileBackend(Path(_TMP) / "secrets.json"))
    with TestClient(app) as c:
        yield c
    reset_secret_store_for_tests(None)


def _post(client, body=b"OggS-fake-audio"):
    return client.post("/api/voice/transcribe", content=body, headers={"Content-Type": "audio/webm;codecs=opus"})


def test_needs_a_groq_key(client):
    r = _post(client)
    assert r.status_code == 409 and "Groq API key" in r.json()["detail"]


def test_empty_audio_is_rejected(client):
    get_secret_store().set(GROQ_API_KEY, "gsk_test")
    assert _post(client, b"").status_code == 400


@respx.mock
def test_forwards_audio_and_returns_text(client):
    get_secret_store().set(GROQ_API_KEY, "gsk_test")
    db = SessionLocal()
    db.add(Issue(jira_id="v1", issue_key="PPVM-1", project_key="PPVM", summary="x"))
    db.commit()
    db.close()
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"text": " Still on PPVM-123. "}))
    r = _post(client)
    assert r.status_code == 200 and r.json() == {"text": "Still on PPVM-123."}
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer gsk_test"
    body = req.content
    assert b"whisper-large-v3-turbo" in body and b"OggS-fake-audio" in body
    assert b"PPVM-123" in body  # project keys prime the vocabulary
    assert b'filename="checkin.webm"' in body


@respx.mock
def test_bad_key_maps_to_409(client):
    get_secret_store().set(GROQ_API_KEY, "gsk_bad")
    respx.post(URL).mock(return_value=httpx.Response(401, json={"error": "invalid"}))
    r = _post(client)
    assert r.status_code == 409 and "rejected" in r.json()["detail"]
