"""Phone companion: pairing, token auth, revocation, and the timer routes."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jt-mobile-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SECRET_BACKEND"] = "file"
os.environ["LOG_DIR"] = f"{_TMP}/logs"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, reset_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.mobile import pairing  # noqa: E402
from app.mobile.server import mobile_app  # noqa: E402
from app.models import Issue, MobileDevice, WorkSession  # noqa: E402
from app.secrets import FileBackend, reset_secret_store_for_tests  # noqa: E402


@pytest.fixture(scope="module")
def laptop():
    reset_engine_for_tests(f"sqlite:///{_TMP}/test.db")
    reset_secret_store_for_tests(FileBackend(Path(_TMP) / "secrets.json"))
    with TestClient(app) as c:
        yield c
    reset_secret_store_for_tests(None)


@pytest.fixture(scope="module")
def phone(laptop):
    return TestClient(mobile_app)


@pytest.fixture(scope="module")
def token(laptop, monkeypatch_module):
    monkeypatch_module.setattr(pairing, "lan_ip", lambda: "192.168.1.20")
    import app.routers.mobile as mobile_router

    monkeypatch_module.setattr(mobile_router, "lan_ip", lambda: "192.168.1.20")
    r = laptop.post("/api/mobile/pair", json={"name": "Pixel"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith("http://192.168.1.20:8757/m/#t=")
    assert body["qr_svg"].startswith("<svg")
    assert [d["name"] for d in body["devices"]] == ["Pixel"]
    return body["url"].split("#t=", 1)[1]


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_token_is_stored_only_as_a_hash(token):
    db = SessionLocal()
    try:
        rows = db.query(MobileDevice).all()
        assert all(token not in (r.token_hash or "") for r in rows)
        assert rows[0].token_hash == pairing.hash_token(token)
    finally:
        db.close()


def test_phone_api_rejects_missing_or_wrong_token(phone, token):
    assert phone.get("/api/m/state").status_code == 401
    assert phone.get("/api/m/state", headers=_auth("nope")).status_code == 401


def test_phone_page_is_public_but_api_is_not(phone):
    r = phone.get("/m/")
    assert r.status_code == 200 and "Jira Tracker" in r.text
    assert phone.get("/m/manifest.webmanifest").status_code == 200


def test_mobile_app_exposes_no_laptop_routes(phone, token):
    # Settings, auth, sessions etc. must not exist on the LAN-facing app.
    for path in ("/api/settings", "/api/auth/status", "/api/sessions", "/api/mobile"):
        assert phone.get(path, headers=_auth(token)).status_code == 404


def test_start_switch_pause_resume_stop(phone, token):
    db = SessionLocal()
    try:
        db.add(Issue(jira_id="1", issue_key="PAY-7", summary="Fix webhook retries"))
        db.commit()
    finally:
        db.close()

    h = _auth(token)
    s = phone.post("/api/m/start", json={"issue_key": "pay-7"}, headers=h).json()
    assert s["session"]["issue_key"] == "PAY-7"
    assert s["session"]["description"] == "Fix webhook retries"
    assert s["tz"] == "Asia/Kolkata"

    assert phone.post("/api/m/pause", headers=h).json()["session"]["state"] == "paused"
    assert phone.post("/api/m/resume", headers=h).json()["session"]["state"] == "active"

    # Switching finishes the running session (no Jira connection here, so it is
    # saved locally with a warning) and starts the new one.
    s = phone.post("/api/m/start", json={"description": "Code review"}, headers=h).json()
    assert s["session"]["description"] == "Code review"
    assert s["session"]["issue_key"] is None

    s = phone.post("/api/m/stop", headers=h).json()
    assert s["session"] is None
    db = SessionLocal()
    try:
        states = [w.state for w in db.query(WorkSession).all()]
        assert states == ["completed", "completed"]
    finally:
        db.close()


def test_start_requires_something_to_track(phone, token):
    r = phone.post("/api/m/start", json={}, headers=_auth(token))
    assert r.status_code == 422


def test_ticket_search(phone, token):
    r = phone.get("/api/m/tickets?q=webhook", headers=_auth(token))
    assert [t["issue_key"] for t in r.json()] == ["PAY-7"]
    recent = phone.get("/api/m/tickets", headers=_auth(token)).json()
    assert recent[0]["issue_key"] == "PAY-7"


def test_revoked_device_is_locked_out(laptop, phone, token):
    device_id = laptop.get("/api/mobile").json()["devices"][0]["id"]
    r = laptop.delete(f"/api/mobile/devices/{device_id}")
    assert r.status_code == 200 and r.json()["devices"] == []
    assert phone.get("/api/m/state", headers=_auth(token)).status_code == 401


def test_wifi_address_beats_virtual_adapters():
    mp = pytest.MonkeyPatch()
    # Default route via the WSL switch, plus Wi-Fi, link-local and loopback.
    mp.setattr(pairing, "_route_ip", lambda target: "172.18.192.1")
    mp.setattr(
        pairing.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", (ip, 0)) for ip in
                         ("169.254.10.1", "192.168.228.5", "127.0.0.1", "10.0.0.7")],
    )
    try:
        assert pairing.lan_ips() == ["192.168.228.5", "10.0.0.7", "172.18.192.1"]
    finally:
        mp.undo()


def test_qr_svg_scales_without_cropping():
    svg = pairing.qr_svg("http://192.168.1.20:8757/m/#t=" + "x" * 43)
    # A viewBox (and no fixed size) lets CSS scale it instead of clipping it.
    assert "viewBox=" in svg
    assert 'width="' not in svg.split(">", 1)[0]
