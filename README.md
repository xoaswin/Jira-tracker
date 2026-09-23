# Work Session Tracker with Jira Sync

A small local app that sits in front of Jira and makes logging work take five
seconds instead of five minutes. You type what you are working on, pick a board,
choose the ticket, run a timer, and the app pushes a worklog and comment to the
real Jira issue.

Local first: a work session lives in local SQLite and is the source of truth for
in-flight work. Jira is a sync target.

## Status

All five phases are complete and tested. The app connects to Jira, caches boards
and issues, ranks tickets against a plain-language description (with git branch
and explicit issue-key detection), drafts and creates new stories or subtasks
with a duplicate guard, runs a timer with pause and resume, and pushes worklogs
and comments through a durable outbox that retries with backoff and never
duplicates a worklog. AI (local Ollama by default, optional Gemini or Groq)
polishes drafts and comments but is never required: the app is fully usable with
AI turned off. See the feature list below.

## Features

- Connect to Jira Cloud, validated against /myself; token in the OS keychain.
- Board and issue caching with on-demand and background refresh.
- Local ranked matching (section 6): BM25 plus optional semantic embeddings plus
  a recency boost, with explicit ABC-123 key extraction and git branch prefill.
- Issue creation (section 5.5): createmeta-driven required fields, a
  story-versus-subtask rule, a 0.8-similarity duplicate guard, and a confirmation
  dialog with every field editable. Nothing is written to Jira without a click.
- Durable outbox (section 5.7 and 5.8): retry with backoff respecting
  Retry-After, a worklog idempotency check before every retry, and a 401 halt
  that flags reauthentication instead of burning retries.
- Optional status transition on finish (for example, move the ticket to Done),
  skipped silently if the workflow has no such transition.
- AI, deliberately narrow (section 8): draft an issue, tidy a worklog comment,
  and a daily standup summary. Hard 10 second timeout, silent fallback to raw
  text, and a small "AI unavailable" indicator. Ollama is the default and stays
  on your machine; Gemini and Groq are opt-in with a clear warning.
- Idle detection with a keep-or-subtract prompt, and an end-of-day nudge banner.
- Dashboard: today's sessions with sync status, a weekly tracked-versus-logged
  chart, and an unlogged-sessions panel with retry.

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy 2 on SQLite, Alembic, httpx,
  keyring, APScheduler, pydantic-settings.
- Frontend: React 18, Vite, TypeScript, Tailwind, TanStack Query, Zustand,
  lucide-react.
- One process in production: FastAPI serves the built frontend on port 8756.

## Quick start

### Prerequisites

- Python 3.11+ (`python3 --version`)
- Node 18+ and npm (`node --version`)
- `make` and a POSIX shell (bash). Comes standard on Linux and macOS.
  **On Windows, use WSL2** (`wsl --install` from an admin PowerShell, then
  clone and run everything inside the WSL distro) — the launcher script is
  bash, and the Makefile assumes a Unix venv layout. Native `cmd.exe`/
  PowerShell without WSL is not supported out of the box.
- git

### 1. Clone

```
git clone https://github.com/xoaswin/Jira-tracker.git
cd Jira-tracker
```

### 2. Install dependencies

```
make install
```

That creates the backend virtualenv, installs Python and Node dependencies.
No `.env` file is required to get started — every setting has a working
default and the app is fully configured from the UI (see step 4). Only copy
`.env.example` to `.env` if you want to override a default up front (for
example `GIT_REPO_PATHS` for the git-diff-to-worklog feature, or
`AI_PROVIDER`).

### 3. Run

Run both dev servers (FastAPI on 8756, Vite on 5173 proxying /api):

```
make dev
```

### 4. Connect to Jira

Open http://localhost:5173, go to Settings, and connect with your Jira base URL,
email, and an API token (create one at id.atlassian.com under Security, API
tokens). The token is stored in your OS keychain, never in the database or a
file in the repo.

If you're on WSL2 and opening the app from a Windows browser, both dev servers
already bind `0.0.0.0` so `http://localhost:5173` is reachable across the
WSL2 boundary without extra config.

Production single process:

```
make build      # emits frontend/dist
make backend    # or: cd backend && . .venv/bin/activate && python -m uvicorn app.main:app --port 8756
```

Then open http://localhost:8756.

## Testing

```
make test            # backend (pytest) + frontend (vitest)
make test-backend
make test-frontend
```

The Jira API is fully mocked with respx. No test hits a real Jira instance. The
suite covers the known API traps: the exact worklog datetime format across
timezones (including a half-hour offset and millisecond padding), ADF round
trips and the None or plain-string or dict description cases, duration maths with
pauses and manual overrides, and the full connect to push flow end to end.

## Architecture notes

- The Jira client redacts the Authorization header in every log line and writes
  a rotating request and response log to backend/logs/jira.log, with bodies for
  non-2xx responses. Jira error bodies are surfaced in the UI, because they are
  the only clue to what field was wrong.
- Datetimes are stored as UTC and always returned timezone aware, so SQLite's
  lack of tzinfo never leaks naive datetimes into the timer maths.
- Migrations run automatically on startup, and can also be applied with
  make migrate.

## Security

- The API token lives in the OS keychain via keyring. On a headless machine with
  no keychain backend (for example WSL), it falls back to a 0600 file in your
  home directory, outside the repo. It is never written to the database, a config
  file in the project, or any log line.

## Optional: semantic matching

Matching works out of the box with BM25 keyword ranking plus a recency boost.
For semantic matching (catching paraphrases), install the optional embedding
model. It pulls in torch, so use a CPU-only wheel to avoid the CUDA stack:

```
cd backend && . .venv/bin/activate
pip install sentence-transformers --extra-index-url https://download.pytorch.org/whl/cpu
```

The ranker detects the model on startup and rebuilds issue embeddings in the
background. If it is not installed, the app redistributes the ranking weights
and works exactly as before.

## Optional: local AI with Ollama

AI is off-machine-free by default. Install Ollama and pull a model to enable
drafting and comment cleanup locally:

```
ollama pull llama3.1:8b
```

Then select Ollama in Settings (it is the default). Gemini and Groq are also
selectable there for cloud generation, with keys stored in the keychain.
