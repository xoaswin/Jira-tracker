"""The Jira HTTP layer: auth, logging, and loud structured errors.

Phase 1 uses this client for direct synchronous calls (search, worklog, comment,
create). The retry / backoff / rate-limit policy for the outbox worker lands in
Phase 2; this client's job is to make one request, log it, and either return the
parsed body or raise a :class:`JiraError` that carries Jira's real response body
(rule 8: fail loudly with the actual body, because Jira's error text is the only
clue to what field was wrong).

Rules honoured here:
  * Rule 4: the ``Authorization`` header is redacted in every log line.
  * Rule 7: every request and response status is logged to a rotating file, with
    bodies included for non-2xx responses.
"""

from __future__ import annotations

import base64
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("jira_tracker.jira")

_REDACTED = "Basic ***REDACTED***"


def configure_jira_logging(log_dir: str, level: str = "INFO") -> None:
    """Attach a rotating file handler for Jira traffic (idempotent)."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / "jira.log"
    # Avoid duplicate handlers on repeated calls (reload, tests).
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) and getattr(h, "_jira_handler", False):
            return
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5)
    handler._jira_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level.upper())


def normalize_base_url(raw: str) -> str:
    """Reduce any pasted Jira URL to the site root ``https://host``.

    Users often paste a full board or project URL, e.g.
    ``https://acme.atlassian.net/jira/software/c/projects/PAY/boards/534``.
    The REST client must call ``https://acme.atlassian.net/rest/api/3/...``, so
    we strip the path, query, and fragment and keep only scheme + host. A bare
    host (no scheme) is assumed to be https.
    """
    raw = (raw or "").strip()
    if not raw:
        return raw
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    scheme = parsed.scheme or "https"
    host = parsed.netloc or parsed.path.split("/")[0]
    return f"{scheme}://{host}".rstrip("/")


def _redact(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with any Authorization value masked."""
    safe = dict(headers)
    for k in list(safe.keys()):
        if k.lower() == "authorization":
            safe[k] = _REDACTED
    return safe


class JiraError(Exception):
    """A non-2xx response (or transport failure) from Jira.

    ``status_code`` is None for transport-level errors (timeout, connection).
    ``body`` preserves Jira's raw response text for surfacing in the UI.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any = None,
        method: str | None = None,
        url: str | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body
        self.method = method
        self.url = url
        self.retry_after = retry_after

    def is_permanent(self) -> bool:
        """400/401/403/404 are permanent for this payload (section 5.7)."""
        return self.status_code in (400, 401, 403, 404)

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "status_code": self.status_code,
            "body": self.body,
            "method": self.method,
            "url": self.url,
            "retry_after": self.retry_after,
        }


class JiraClient:
    """Thin authenticated wrapper over httpx for Jira Cloud."""

    def __init__(
        self,
        base_url: str,
        email: str,
        token: str,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = normalize_base_url(base_url)
        self.email = email
        self._auth = self._basic_auth(email, token)
        self._timeout = timeout
        # Allow injecting an httpx.Client (tests use respx against a real client).
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    @staticmethod
    def _basic_auth(email: str, token: str) -> str:
        raw = f"{email}:{token}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _headers(self, extra: dict | None = None) -> dict[str, str]:
        headers = {
            "Authorization": self._auth,
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
    ) -> Any:
        """Make one request. Return parsed JSON on 2xx, else raise JiraError."""
        url = f"{self.base_url}{path}"
        headers = self._headers(
            {"Content-Type": "application/json"} if json_body is not None else None
        )

        logger.info("REQ %s %s params=%s headers=%s", method, url, params, _redact(headers))

        try:
            resp = self._client.request(
                method, url, params=params, json=json_body, headers=headers
            )
        except httpx.TimeoutException as exc:
            logger.error("TIMEOUT %s %s: %s", method, url, exc)
            raise JiraError(
                f"Timeout calling Jira: {exc}", method=method, url=url
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("TRANSPORT-ERROR %s %s: %s", method, url, exc)
            raise JiraError(
                f"Connection error calling Jira: {exc}", method=method, url=url
            ) from exc

        if resp.is_success:
            logger.info("RESP %s %s -> %s", method, url, resp.status_code)
            if resp.status_code == 204 or not resp.content:
                return None
            try:
                return resp.json()
            except ValueError:
                return resp.text

        # Non-2xx: log the body (rule 7) and raise loudly (rule 8).
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
        logger.error(
            "RESP %s %s -> %s body=%s retry_after=%s",
            method,
            url,
            resp.status_code,
            body,
            retry_after,
        )
        raise JiraError(
            f"Jira returned {resp.status_code} for {method} {path}",
            status_code=resp.status_code,
            body=body,
            method=method,
            url=url,
            retry_after=retry_after,
        )

    def get(self, path: str, *, params: dict | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, json_body: Any = None, params: dict | None = None) -> Any:
        return self.request("POST", path, params=params, json_body=json_body)

    def myself(self) -> dict:
        """Validate the token and return the current user's account info."""
        return self.get("/rest/api/3/myself")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "JiraClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        # HTTP-date form is possible but Jira sends seconds; ignore date form.
        return None
