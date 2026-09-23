"""Secret storage for the Jira API token (and later, AI provider keys).

Rule 4 (section 15): never put the API token in the database, in a config file
that could be committed, or in a log line. Keychain only.

Reality: a headless machine (WSL, CI, a server) may have no OS keyring backend.
So this module exposes a single ``SecretStore`` interface with two backends:

* ``KeyringBackend`` - the real OS keychain via the ``keyring`` package. Used
  whenever a working backend is present. This is the default and preferred path.
* ``FileBackend``    - a fallback that writes to ``~/.jira-tracker/secrets.json``
  with ``0600`` permissions, OUTSIDE the repository, never committed. This is the
  same approach ``git credential-store`` uses when no keychain is available.

Either way the token never touches the project directory, the SQLite database, or
any log line.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger("jira_tracker.secrets")

# Keys used within the store. Kept here so nothing else hardcodes the strings.
JIRA_TOKEN_KEY = "jira_api_token"
# AI provider keys (section 8): also keychain-only, never in config or the DB.
GEMINI_API_KEY = "gemini_api_key"
GROQ_API_KEY = "groq_api_key"


class SecretStore:
    """Minimal secret store interface."""

    def get(self, key: str) -> str | None:  # pragma: no cover - interface
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def kind(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class KeyringBackend(SecretStore):
    def __init__(self, service: str):
        import keyring

        self._keyring = keyring
        self._service = service

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(self._service, key)

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(self._service, key, value)

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(self._service, key)
        except Exception:
            # Deleting a non-existent entry must not raise.
            pass

    @property
    def kind(self) -> str:
        return "keyring"


class FileBackend(SecretStore):
    """0600 JSON file in the user's home dir, never in the repo."""

    def __init__(self, path: Path | None = None):
        self._path = path or (Path.home() / ".jira-tracker" / "secrets.json")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        # Write then lock down permissions to owner read/write only.
        self._path.write_text(json.dumps(data))
        try:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # e.g. Windows-mounted filesystems; best effort.

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._read()
        data[key] = value
        self._write(data)

    def delete(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self._write(data)

    @property
    def kind(self) -> str:
        return "file"


def _keyring_is_usable(service: str) -> bool:
    """Probe whether a real keyring backend can actually store a secret."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        backend = keyring.get_keyring()
        if isinstance(backend, FailKeyring):
            return False
        # Round-trip a probe value to be sure the backend truly works.
        probe = "__probe__"
        keyring.set_password(service, probe, "1")
        ok = keyring.get_password(service, probe) == "1"
        keyring.delete_password(service, probe)
        return ok
    except Exception:
        return False


def build_secret_store(backend: str, service: str) -> SecretStore:
    """Construct a SecretStore per the configured backend preference."""
    if backend == "keyring":
        return KeyringBackend(service)
    if backend == "file":
        return FileBackend()
    # auto
    if _keyring_is_usable(service):
        logger.info("Using OS keyring backend for secret storage.")
        return KeyringBackend(service)
    logger.warning(
        "No usable OS keyring backend found. Falling back to a 0600 file at "
        "~/.jira-tracker/secrets.json (outside the repo). The token is never "
        "written to the project directory, the database, or any log."
    )
    return FileBackend()


# A module-level default store, lazily built from settings on first access.
_default_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    global _default_store
    if _default_store is None:
        from app.config import get_settings

        s = get_settings()
        _default_store = build_secret_store(s.secret_backend, s.keyring_service)
    return _default_store


def reset_secret_store_for_tests(store: SecretStore | None) -> None:
    """Test hook to inject a store (or reset to lazy default)."""
    global _default_store
    _default_store = store
