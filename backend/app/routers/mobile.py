"""Phone pairing routes (laptop side; the main app is loopback-only).

    GET    /api/mobile               -> listener status, LAN address, devices
    POST   /api/mobile/pair          -> mint a device token, return QR + URL
    DELETE /api/mobile/devices/{id}  -> revoke a phone

The phone itself talks to ``app.mobile.server`` on the LAN port.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.mobile import server
from app.mobile.pairing import (
    active_devices,
    create_device,
    lan_ip,
    lan_ips,
    pairing_url,
    qr_svg,
    revoke,
)

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


class PairRequest(BaseModel):
    name: str | None = None


def _device(d) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "user_agent": d.user_agent,
    }


def _status(db: Session) -> dict:
    return {
        "running": server.is_running(),
        "port": get_settings().mobile_port,
        "lan_ip": lan_ip(),
        "devices": [_device(d) for d in active_devices(db)],
    }


@router.get("")
def mobile_status(db: Session = Depends(get_db)) -> dict:
    return _status(db)


@router.post("/pair")
def pair(req: PairRequest, db: Session = Depends(get_db)) -> dict:
    ip = lan_ip()
    if ip is None:
        raise HTTPException(
            status_code=409,
            detail="This laptop isn't on a network right now. Connect to Wi-Fi and try again.",
        )
    device, token = create_device(db, req.name or "Phone")
    server.start_listener()
    port = get_settings().mobile_port
    url = pairing_url(ip, port, token)
    # Other addresses to try if the phone can't reach the first guess (e.g. a
    # laptop on both Wi-Fi and a wired/VPN network).
    alternates = [pairing_url(alt, port, token) for alt in lan_ips() if alt != ip]
    return {
        **_status(db),
        "device": _device(device),
        "url": url,
        "qr_svg": qr_svg(url),
        "alternate_urls": alternates,
    }


@router.delete("/devices/{device_id}")
def unpair(device_id: int, db: Session = Depends(get_db)) -> dict:
    if revoke(db, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if not active_devices(db):
        server.stop_listener()
    return _status(db)
