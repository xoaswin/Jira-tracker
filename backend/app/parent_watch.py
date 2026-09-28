"""Exit when the desktop shell that spawned us goes away.

Electron's ``before-quit`` kills the backend on a normal quit, but a crash or a
force-kill of the shell skips that and leaves an orphan holding port 8756 (so
the next launch can't start its own backend). The shell passes its pid in
``JT_PARENT_PID``; a daemon thread waits on that process and hard-exits us when
it ends. No-op when the variable is unset (dev server, tests).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

logger = logging.getLogger("jira_tracker.parent_watch")

_POLL_SECONDS = 3.0


def _wait_windows(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return  # already gone (or not ours to open): treat as exited
    try:
        kernel32.WaitForSingleObject(handle, INFINITE)
    finally:
        kernel32.CloseHandle(handle)


def _wait_posix(pid: int) -> None:
    while True:
        try:
            os.kill(pid, 0)  # signal 0 = existence check on POSIX only
        except ProcessLookupError:
            return
        except PermissionError:
            pass  # exists, owned by someone else
        time.sleep(_POLL_SECONDS)


def _watch(pid: int) -> None:
    try:
        if sys.platform == "win32":
            _wait_windows(pid)
        else:
            _wait_posix(pid)
    except Exception:  # noqa: BLE001 - never kill the backend on a watcher bug
        logger.exception("parent watcher failed; backend will keep running")
        return
    logger.warning("desktop shell (pid %s) exited; shutting the backend down", pid)
    os._exit(0)


def watch_parent_process() -> None:
    raw = os.environ.get("JT_PARENT_PID")
    if not raw:
        return
    try:
        pid = int(raw)
    except ValueError:
        return
    threading.Thread(target=_watch, args=(pid,), name="parent-watch", daemon=True).start()
