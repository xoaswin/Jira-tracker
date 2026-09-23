# Project Context — Work Session Tracker with Jira Sync

A local-first desktop-style web app that sits in front of Jira and makes logging
work take seconds. You describe what you're doing, pick a board, choose a ticket,
run a timer, and the app pushes a worklog + comment to the real Jira issue. Local
SQLite is the source of truth for in-flight work; Jira is a sync target.

This file is a hand-off for future sessions: architecture, conventions, and the
full feature set including everything added beyond the original five phases.

## Stack

- **Backend:** Python 3.11+ (runs on 3.14 here), FastAPI, SQLAlchemy 2 on SQLite,
  Alembic, httpx, keyring, APScheduler, pydantic-settings.
- **Frontend:** React 18, Vite, TypeScript, Tailwind, TanStack Query (server
  state), Zustand (UI state), lucide-react icons.
- **One process in prod:** FastAPI serves the built frontend (`frontend/dist`) on
  port 8756.

## Running (WSL2 → Windows browser)

The dev servers must bind `0.0.0.0` so a Windows browser can reach them across
the WSL2 boundary (127.0.0.1 inside the VM is invisible from Windows). Both are
already configured for this: `make backend` / `run.sh` pass `--host 0.0.0.0`, and
`vite.config.ts` sets `server.host = true`.

- `make dev` (or `./run.sh`) — FastAPI 8756 + Vite 5173 (proxies `/api`). Use this.
- Open **http://localhost:5173** from Windows (or the WSL IP if localhost
  forwarding is off, e.g. `http://172.x.x.x:5173`).
- `make build && make backend` — single process on 8756.
- **Caveat:** `vite build` is very slow on the WSL↔OneDrive filesystem (can exceed
  2 min). `tsc --noEmit` + the Vite dev server are the fast dev loop; only build
  for a real prod bundle.

## Testing

- Backend: `cd backend && . .venv/bin/activate && python -m pytest -q`
  (currently **198 passing**). Jira is fully mocked with respx; no test hits a
  real instance. Background outbox poller is disabled under pytest.
- Frontend: `cd frontend && npx vitest run` (**31 passing**) and
  `npx tsc --noEmit`. Pure logic (time, gaps, work-window) is unit-tested;
  components are not.

## Core conventions (follow these)

1. **AI is never load-bearing.** Every AI call goes through
   `app/ai/factory.py::safe_generate`, which enforces a timeout and silently
   falls back to `NullProvider`, returning `(text, used_ai)`. The app is fully
   usable with AI off. UIs show a small "AI unavailable / off" hint on fallback.
2. **Never lose a session.** Completed sessions are saved locally first, then
   pushed via the durable **outbox** (`app/sync/`), which retries with backoff,
   does a worklog idempotency check, and halts on 401 (flags `needs_reauth`)
   instead of burning retries.
3. **Surface Jira's real error body** (rule 8). The Jira client redacts auth
   headers in logs but preserves error bodies; routes return them; the UI shows
   them (they're the only clue to what field was wrong). `JiraError` → 401 maps to
   a reauth signal, else 502.
4. **UTC everywhere in storage.** `app/db.py::UTCDateTime` stores naive-UTC and
   returns tz-aware UTC, so SQLite's lack of tzinfo never leaks naive datetimes.
   **The backend's own timezone defaults to UTC** — so anything about "the
   workday" or "today in the user's clock" is computed **client-side** in local
   time (see gap detection and the work-window prompts).
5. **Worklog datetime format is strict** (`app/jira/datetime_fmt.py`):
   `yyyy-MM-dd'T'HH:mm:ss.SSSZ` with a colon-free offset and mandatory 3-digit
   millis. Jira's minimum worklog is 60s; shorter is rounded up and flagged.
6. **No em dashes** in any generated/user-facing text (stated in every AI system
   prompt too).
7. **Never interpolate into a shell.** All git calls use `subprocess.run` with an
   argument list and `shell=False`, timeout-guarded, and never raise (they
   degrade to empty results).
8. **Migrations run automatically on startup** (`app/db_init.py`). Current head:
   **`d4f6b1a2c8e9`**. Add a migration for any model change.

## Layout

```
backend/app/
  ai/            provider factory + Ollama/Gemini/Groq/Null + prompts
  integrations/  git.py (branch/commits/diffstat, all shell=False, never-raise)
  jira/          client, issues, worklogs, transitions, editmeta, adf, datetime_fmt
  matching/      BM25 + embeddings + ranker (deterministic, local)
  routers/       auth, boards, issues, sessions, outbox, match, reports,
                 settings, manage, my_tickets (also hosts /plan/today)
  services/      connection, push, repush, drafting, matching, reports, ai_text,
                 manage, my_tickets, velocity, planning
  models.py schemas.py db.py config.py main.py
frontend/src/
  api/           client.ts (typed fetch), hooks.ts (TanStack), types.ts
  components/    ui.tsx primitives, ManagePanel, GapDetection,
                 DailyCompletenessNudge, CheckinPrompt, PlanMyDay, AISettings, ...
  screens/       Start, Match, ActiveSession, Finish, Dashboard, MyTickets,
                 Manage, Settings
  lib/           time.ts, gaps.ts, idle.ts (+ work-window helpers)
  store/ui.ts    Zustand: screen nav + a few persisted prefs
```

## Feature set

**Original five phases (all complete):** Jira connect (token in OS keychain),
board/issue caching, local ranked matching (BM25 + optional embeddings + recency,
explicit `ABC-123` extraction, git-branch prefill), issue creation
(createmeta-driven, story-vs-subtask rule, 0.8 duplicate guard), timer with
pause/resume, durable outbox push, optional status transition on finish, narrow
AI (draft issue / cleanup comment / daily summary), idle detection, end-of-day
nudge, dashboard (today + weekly tracked-vs-logged chart + unlogged panel).

**Added since (this app is being pushed well beyond the original spec):**

- **Manage screen** — open one or many tickets (stacked collapsible cards):
  edit date fields (start/due/actual, discovered via editmeta), drive the
  workflow with an auto-walk that never overshoots the target category,
  block "Mark Done" until all subtasks are Done, per-subtask date editing.
- **Full management inline in Active Session** — the same `ManagePanel` renders
  under the timer for the attached ticket.
- **Log worklogs from Manage** — `POST /api/manage/{key}/worklog` (+ list),
  hours/minutes/started/comment; shown in `ManagePanel` with recent worklogs.
- **Assignee on the match list** — sync now captures `assignee_name`; the "what
  are you working on" candidates show a green **Mine** badge / the assignee's
  name / Unassigned (`is_mine` computed vs the connected account id).
- **My Tickets screen** — `GET /api/my-tickets`, live `assignee = currentUser()`,
  grouped by due-date urgency (overdue / due_today / due_soon / scheduled /
  no_due) with counts; per-row Start (timer) and Manage (deep-link) actions.
- **AI standup summary on the Dashboard** — surfaces the pre-existing
  `/api/reports/daily-summary` with copy/regenerate.
- **AI copilot: git-diff → worklog** (signature feature) — on Finish, "Draft from
  commits" gathers the branch's commits + diffstat **since the session started**
  and drafts the worklog comment. `commits_since`/`diffstat_since` filter by
  parsed committer timestamp in Python because `git log --since` is NOT strict at
  the boundary (it can still return the latest commit). Degrades cleanly:
  no repo → hint; commits but no AI → raw commit list.
- **Gap detection** (`lib/gaps.ts`, pure + tested) — Dashboard panel showing
  stretches of today's work window no session covers, one-click log via the
  manual-session path. All local-clock.
- **Plan My Day** — `GET /api/plan/today?capacity_hours`, ranks My Tickets by
  urgency → priority → due date, estimates each via **learned velocity**
  (`services/velocity.py`: median actual duration per issue type, joined
  `sessions.issue_key → issues.issue_type`), greedily fits to capacity, marks
  overflow. Shown atop My Tickets with a persisted capacity control.
- **Work-window accountability** (settings: `work_start_time`, `work_end_time`,
  `daily_target_hours`, `checkin_interval_minutes`):
  - **Daily completeness nudge** — after work end, if today's tracked total is
    below the daily target, a banner asks what else you did (e.g. 12:00–21:00 day
    with a 1h break → 7.5h target).
  - **Recurring check-in** — every N minutes within work hours, a modal fires
    **whether or not a timer is running**. No session → "What are you working
    on?" (Start). Active session → "Still on <TICKET>?" with "Yes, still on it" /
    "Switch task", to catch a stale timer.
- **Mid-session estimate/budget warning** — `GET /api/velocity/estimate?issue_type=`;
  `EstimateBudget` under the Active timer shows a live "elapsed of ~estimate"
  bar (green/amber/rose) and warns when over your usual time for that type.
  Estimate is the learned median; falls back to overall/1h-default and says
  "rough" when there's no per-type history.
- **Reassign + priority in Manage** — `ManageView` carries assignee + priority;
  `jira/people.py` provides assignable-user type-ahead
  (`/user/assignable/search`), the global priority list, `PUT .../assignee`
  (accountId, null unassigns), and `PUT .../priority`. `AssigneeAndPriority` in
  `ManagePanel` renders a people picker + priority dropdown.
- **Session history** — `SessionHistory` on the Dashboard: a date picker queries
  the sessions list's `from`/`to` range (local-day bounds → ISO instants) and
  shows that day's sessions + tracked total. No backend change (range filter
  already existed).

## User context

- Runs the backend in **WSL**, uses the app from a **Windows** browser.
- Work hours **12:00–21:00 IST**, 1h break → **7.5h daily target**. Wants an
  hourly "what are you working on?" check-in that fires even during an active
  session (to confirm it's still the same task).
- Direction: wants the app to "think big" and solve multiple real problems, not
  just be a nicer Jira skin. The winning theme is the overlap of **time + git +
  Jira + AI** locally — things no single external tool can do.

## Likely next ideas (not yet built)

- Labels / story-points / epic-link in Manage (assignee + priority are done).
- Weekly "brag doc" / self-review; Slack export of the standup.
- Commit-driven session suggestions ("3 commits on PAY-431 not yet logged").
- Bulk actions across My Tickets; in-app comment thread read/reply.
