import subprocess
import sys
import time

from app import parent_watch


def test_noop_without_env(monkeypatch):
    monkeypatch.delenv("JT_PARENT_PID", raising=False)
    parent_watch.watch_parent_process()  # must not start anything or raise


def test_watcher_returns_when_parent_exits(monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    exited = []
    monkeypatch.setattr(parent_watch, "_POLL_SECONDS", 0.05)
    monkeypatch.setattr(parent_watch.os, "_exit", lambda code: exited.append(code))
    start = time.time()
    # Reap the child in the background so it doesn't linger as a zombie
    # (a zombie still "exists" to kill(pid, 0)).
    import threading
    threading.Thread(target=child.wait, daemon=True).start()
    parent_watch._watch(child.pid)
    assert exited == [0]
    assert time.time() - start < 5
