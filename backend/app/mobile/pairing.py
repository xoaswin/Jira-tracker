"""Device tokens, the laptop's LAN address, and the pairing QR code."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import socket
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MobileDevice, utcnow

# Don't write last_seen on every poll (the phone polls every few seconds).
_SEEN_RESOLUTION = timedelta(minutes=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_device(db: Session, name: str = "Phone") -> tuple[MobileDevice, str]:
    """Mint a device and return it with its plaintext token (shown once)."""
    token = secrets.token_urlsafe(32)
    device = MobileDevice(name=name.strip() or "Phone", token_hash=hash_token(token))
    db.add(device)
    db.commit()
    db.refresh(device)
    return device, token


def active_devices(db: Session) -> list[MobileDevice]:
    return list(
        db.execute(
            select(MobileDevice)
            .where(MobileDevice.revoked_at.is_(None))
            .order_by(MobileDevice.created_at.desc())
        )
        .scalars()
        .all()
    )


def authenticate(db: Session, token: str | None, user_agent: str | None = None) -> MobileDevice | None:
    """The non-revoked device owning ``token``, or None."""
    if not token:
        return None
    digest = hash_token(token)
    device = db.execute(
        select(MobileDevice).where(MobileDevice.token_hash == digest)
    ).scalar_one_or_none()
    # Constant-time re-check (the indexed lookup already matched exactly).
    if device is None or not hmac.compare_digest(device.token_hash, digest):
        return None
    if device.revoked_at is not None:
        return None
    now = utcnow()
    if device.last_seen_at is None or now - device.last_seen_at > _SEEN_RESOLUTION:
        device.last_seen_at = now
        if user_agent:
            device.user_agent = user_agent[:200]
        db.commit()
    return device


def revoke(db: Session, device_id: int) -> MobileDevice | None:
    device = db.get(MobileDevice, device_id)
    if device is None:
        return None
    if device.revoked_at is None:
        device.revoked_at = utcnow()
        db.commit()
    return device


def _route_ip(target: str) -> str | None:
    """The local address the OS would use to reach ``target``. Connecting a
    UDP socket sends no packets; it only resolves the route."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _rank(ip: str) -> int:
    """Lower is better. Home/office Wi-Fi is almost always 192.168.x or 10.x;
    172.16-31.x is usually a WSL / Hyper-V / Docker virtual switch that a phone
    can't reach, and 169.254.x / 127.x are never reachable."""
    a, b = (int(p) for p in ip.split(".")[:2])
    if a == 127 or (a == 169 and b == 254):
        return 99
    if a == 192 and b == 168:
        return 0
    if a == 10:
        return 1
    if a == 172 and 16 <= b <= 31:
        return 3
    return 2


def lan_ips() -> list[str]:
    """Candidate IPv4 addresses a phone on the Wi-Fi could reach, best first."""
    found: list[str] = []
    for ip in (_route_ip("8.8.8.8"), _route_ip("10.255.255.255")):
        if ip and ip not in found:
            found.append(ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    usable = [ip for ip in found if _rank(ip) < 99]
    # Stable sort: keeps the default-route address first within a rank.
    return sorted(usable, key=_rank)


def lan_ip() -> str | None:
    """The best guess at the laptop's Wi-Fi address (see ``lan_ips``)."""
    ips = lan_ips()
    return ips[0] if ips else None


def pairing_url(host: str, port: int, token: str) -> str:
    # The token rides in the fragment: browsers never send it to the server or
    # put it in request logs; the page moves it into local storage.
    return f"http://{host}:{port}/m/#t={token}"


def qr_svg(data: str) -> str:
    import segno

    return segno.make(data, error="m").svg_inline(scale=6, border=2, dark="#111827", light="#ffffff")
