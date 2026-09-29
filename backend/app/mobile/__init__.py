"""Mobile companion: a phone web app served to the local Wi-Fi.

Security model (single-user, local-first):

* The main API stays bound to 127.0.0.1. The phone talks to a *separate*
  FastAPI app (``app.mobile.server``) on ``0.0.0.0:<mobile_port>`` that exposes
  only the handful of timer routes below, never settings, secrets or Jira
  management.
* Every phone API call needs a device token (``Authorization: Bearer``). Tokens
  are minted by pairing from the laptop UI, shown once inside a QR code, and
  stored only as SHA-256 hashes. Revoking a device kills its token.
* The listener only runs while at least one device is paired.
"""
