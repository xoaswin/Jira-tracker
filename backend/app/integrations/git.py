"""Git integration for the start screen (section 9).

High value, low effort, no API cost. From a configured repo path we read:

* the current branch name (``git rev-parse --abbrev-ref HEAD``),
* the last few commit subjects (``git log -5 --pretty=%s``),

and derive a work-description prefill plus an optional issue-key preselect.

Security rule (section 9): never interpolate user-supplied strings into a shell.
Every call uses ``subprocess.run`` with an argument list and ``shell=False``.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# An issue key like PAY-431: one-or-more uppercase alphanumerics, a dash, digits.
ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

# How long a single git call may run. A healthy local repo answers instantly;
# this only guards against a hung filesystem or a huge pack operation.
GIT_TIMEOUT_SECONDS = 5.0


@dataclass
class GitContext:
    """What we learned from a repo, ready to drive the Start screen."""

    repo_path: str
    branch: str | None = None
    commits: list[str] = field(default_factory=list)
    # An issue key extracted from the branch name, if the branch is like
    # ``feature/PAY-431-webhook-retry``. Drives full-confidence preselection.
    issue_key: str | None = None
    # A description prefill built from the branch name and recent commits.
    suggested_text: str = ""
    # Populated instead of the above when the repo could not be read.
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.branch is not None


def _run_git(repo_path: Path, args: list[str]) -> str:
    """Run one git command in ``repo_path`` and return stripped stdout.

    Raises ``subprocess.CalledProcessError`` on non-zero exit and
    ``subprocess.TimeoutExpired`` if it hangs. shell is always False.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def extract_issue_key(text: str | None) -> str | None:
    """Return the first ``ABC-123`` style key found in ``text``, else None."""
    if not text:
        return None
    match = ISSUE_KEY_RE.search(text)
    return match.group(1) if match else None


def _branch_to_words(branch: str) -> str:
    """Turn ``feature/PAY-431-webhook-retry`` into ``webhook retry`` style text.

    Drops a leading prefix segment (feature/, bugfix/, ...), strips any issue
    key (it is surfaced separately), and replaces separators with spaces.
    """
    tail = branch.split("/")[-1]
    tail = ISSUE_KEY_RE.sub(" ", tail)
    words = re.split(r"[-_.]+", tail)
    return " ".join(w for w in words if w).strip()


def read_repo_context(repo_path: str) -> GitContext:
    """Read branch + recent commits from one repo path, never raising.

    Any failure (not a repo, git missing, timeout) is captured in ``error`` so
    the caller can degrade gracefully rather than crash the Start screen.
    """
    ctx = GitContext(repo_path=repo_path)
    path = Path(repo_path).expanduser()
    if not path.exists():
        ctx.error = f"Path does not exist: {repo_path}"
        return ctx
    try:
        ctx.branch = _run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"]) or None
        log_out = _run_git(path, ["log", "-5", "--pretty=%s"])
        ctx.commits = [line for line in log_out.splitlines() if line.strip()]
    except subprocess.CalledProcessError as exc:
        ctx.error = (exc.stderr or "git command failed").strip()
        return ctx
    except subprocess.TimeoutExpired:
        ctx.error = "git command timed out"
        return ctx
    except FileNotFoundError:
        ctx.error = "git executable not found on PATH"
        return ctx

    # Prefer an issue key embedded in the branch; fall back to scanning commits.
    ctx.issue_key = extract_issue_key(ctx.branch) or extract_issue_key(
        " ".join(ctx.commits)
    )

    # Build a prefill from the branch words plus the newest commit subject, so
    # the description box and the matcher both get useful signal.
    parts: list[str] = []
    branch_words = _branch_to_words(ctx.branch or "")
    if branch_words:
        parts.append(branch_words)
    if ctx.commits:
        parts.append(ctx.commits[0])
    ctx.suggested_text = " - ".join(parts).strip()
    return ctx


# Caps so a long session or a huge branch never floods the AI prompt or a log.
_MAX_COMMITS = 30
_MAX_DIFFSTAT_LINES = 60


def _parse_since(since_iso: str) -> datetime | None:
    """Parse the session-start cutoff to an aware datetime, or None if unusable."""
    try:
        from dateutil import parser as _p

        dt = _p.isoparse(since_iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, TypeError):
        return None


def _commits_with_time(path: Path) -> list[tuple[int, str]]:
    """(committer_unix_time, subject) for recent commits on HEAD, newest first.

    Uses a unit-separator between the epoch and subject so subjects containing
    spaces or punctuation parse cleanly.
    """
    out = _run_git(path, ["log", f"-{_MAX_COMMITS}", "--pretty=%ct%x1f%s", "HEAD"])
    rows: list[tuple[int, str]] = []
    for line in out.splitlines():
        if "\x1f" not in line:
            continue
        ts, _, subject = line.partition("\x1f")
        if subject.strip() and ts.strip().isdigit():
            rows.append((int(ts), subject.strip()))
    return rows


def commits_since(repo_path: str, since_iso: str) -> list[str]:
    """Commit subjects on ``repo_path``'s HEAD committed at/after ``since_iso``.

    Newest last. Never raises: returns [] on any failure. We filter by parsed
    committer time in Python rather than trusting ``git log --since``, whose
    date filter is not strict at the boundary (it can still surface the most
    recent commit even for a future cutoff).
    """
    path = Path(repo_path).expanduser()
    if not path.exists():
        return []
    cutoff = _parse_since(since_iso)
    if cutoff is None:
        return []
    cutoff_ts = cutoff.timestamp()
    try:
        rows = _commits_with_time(path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []
    # rows are newest-first; keep those at/after the cutoff, return oldest-first.
    kept = [subject for ts, subject in rows if ts >= cutoff_ts]
    return list(reversed(kept))


def diffstat_since(repo_path: str, since_iso: str) -> str:
    """A compact ``git diff --stat`` of changes since ``since_iso``, capped.

    Diffs the parent of the oldest in-window commit to HEAD, so it reflects what
    changed during the session. Returns "" on any failure or when nothing
    changed in the window.
    """
    path = Path(repo_path).expanduser()
    if not path.exists():
        return ""
    cutoff = _parse_since(since_iso)
    if cutoff is None:
        return ""
    cutoff_ts = cutoff.timestamp()
    try:
        # Oldest-first (hash, time) so we can find the first in-window commit.
        out = _run_git(path, ["log", f"-{_MAX_COMMITS}", "--pretty=%ct%x1f%H", "HEAD", "--reverse"])
        in_window: str | None = None
        for line in out.splitlines():
            ts, _, sha = line.partition("\x1f")
            if ts.strip().isdigit() and int(ts) >= cutoff_ts and sha.strip():
                in_window = sha.strip()
                break
        if in_window is None:
            return ""
        # Diff the in-window base's parent to HEAD; if it has no parent (root
        # commit), diff against the empty tree so the first commit still shows.
        try:
            base = _run_git(path, ["rev-parse", f"{in_window}^"])
            rng = f"{base}..HEAD"
        except subprocess.CalledProcessError:
            rng = in_window  # root commit: diff that commit onward
        stat = _run_git(path, ["diff", "--stat", rng])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    lines = [line for line in stat.splitlines() if line.strip()]
    if len(lines) > _MAX_DIFFSTAT_LINES:
        omitted = len(lines) - _MAX_DIFFSTAT_LINES
        lines = lines[:_MAX_DIFFSTAT_LINES] + [f"... (+{omitted} more files)"]
    return "\n".join(lines)


def commit_counts_by_issue_key(
    repo_paths: list[str], since_iso: str, until_iso: str | None = None
) -> dict[str, int]:
    """Count commits per issue key across all repos in a time window.

    Scans each repo's recent history (all branches via ``--all``), extracts an
    ``ABC-123`` key from each commit subject, and tallies. Filters by parsed
    committer timestamp in Python (``git log --since`` is not strict at the
    boundary). Never raises: a bad repo contributes nothing.
    """
    since = _parse_since(since_iso)
    if since is None:
        return {}
    since_ts = since.timestamp()
    until = _parse_since(until_iso) if until_iso else None
    until_ts = until.timestamp() if until else None

    counts: dict[str, int] = {}
    for repo in repo_paths:
        path = Path(repo).expanduser()
        if not path.exists():
            continue
        try:
            # A generous cap; large windows across all branches stay bounded.
            out = _run_git(path, ["log", "--all", "-500", "--pretty=%ct%x1f%s"])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            continue
        seen_here: set[str] = set()  # de-dupe a commit that lands on many branches
        for line in out.splitlines():
            ts, _, subject = line.partition("\x1f")
            if not ts.strip().isdigit():
                continue
            t = int(ts)
            if t < since_ts or (until_ts is not None and t > until_ts):
                continue
            key = extract_issue_key(subject)
            if not key:
                continue
            dedupe = f"{key}\x1f{subject}\x1f{ts}"
            if dedupe in seen_here:
                continue
            seen_here.add(dedupe)
            counts[key.upper()] = counts.get(key.upper(), 0) + 1
    return counts


def find_repo_for_issue(repo_paths: list[str], issue_key: str) -> str | None:
    """Return the repo whose current branch names ``issue_key``, else None.

    Used to tie a session's ticket back to the repo the work happened in, so we
    can gather that repo's recent commits for the worklog draft.
    """
    if not issue_key:
        return None
    target = issue_key.strip().upper()
    for path in repo_paths:
        ctx = read_repo_context(path)
        if not ctx.ok:
            continue
        if (ctx.issue_key or "").upper() == target:
            return path
    return None


def _head_mtime(repo_path: str) -> float:
    """Modification time of ``.git/HEAD`` for 'which repo is current' ranking."""
    head = Path(repo_path).expanduser() / ".git" / "HEAD"
    try:
        return head.stat().st_mtime
    except OSError:
        return 0.0


def detect_current_context(repo_paths: list[str]) -> GitContext | None:
    """Pick the most recently active repo and return its context.

    "Current" is the repo with the most recently modified ``.git/HEAD``
    (section 9). Repos that fail to read are skipped; if none read, returns the
    first error context so the UI can explain why nothing was detected.
    """
    if not repo_paths:
        return None
    ordered = sorted(repo_paths, key=_head_mtime, reverse=True)
    first_error: GitContext | None = None
    for path in ordered:
        ctx = read_repo_context(path)
        if ctx.ok:
            return ctx
        if first_error is None:
            first_error = ctx
    return first_error
