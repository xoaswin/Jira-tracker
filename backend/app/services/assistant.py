"""The contextual assistant: an agentic, tool-calling chat over the user's data.

Every message gets a compact CONTEXT snapshot (active session, today's tracked
time, plan, ticket counts). Beyond that, the model can FETCH anything on demand
by calling read tools (list/get tickets, worklogs, sessions, week report, plan,
velocity) in a loop, and it can PROPOSE write actions (start a timer, log time,
transition a ticket, set the plan) which are never executed here: they come back
as a ProposedAction the UI confirms and runs against the existing endpoints.

Everything degrades gracefully (no AI provider, Jira unreachable, a failing
tool) and ``run_chat`` never raises.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.chat import ToolCall, safe_chat
from app.ai.prompts import ASSISTANT_SYSTEM
from app.config import get_settings
from app.integrations.git import commits_since, find_repo_for_issue
from app.jira.people import (
    list_priorities,
    search_assignable_users,
    set_assignee,
    set_priority,
)
from app.jira.transitions import walk_to_status
from app.models import AppSettings, DayIntention, WorkSession, utcnow
from app.schemas import AssistantChatRequest, AssistantChatResponse, ProposedAction
from app.services.connection import build_client
from app.services.duration import effective_duration_seconds, live_elapsed_seconds
from app.services.manage import (
    create_subtask,
    edit_dates,
    get_manage_view,
    list_worklogs,
    log_work,
    mark_done,
)
from app.services.my_tickets import get_my_tickets
from app.services.planning import build_day_plan
from app.services.reports import week_report
from app.services.velocity import compute_velocity
from app.services.tz import app_tz, day_bounds
from app.services.tz import today as local_today

logger = logging.getLogger("jira_tracker.assistant")

# Write tools become confirm-gated ProposedActions the UI confirms; execution is
# centralized in execute_action (called by POST /api/assistant/act).
ACTION_TYPES = {
    "start_session",
    "log_worklog",
    "transition_ticket",
    "set_day_plan",
    "mark_done",
    "create_subtask",
    "set_due_date",
    "set_priority",
    "reassign",
}

# Max agentic rounds (each = one model call + its tool executions). Bounds
# latency; real questions almost always resolve in 1-2.
MAX_ITERS = 5

UNAVAILABLE = (
    "I need an AI provider to chat. Open Settings and connect Groq (free) or a "
    "local Ollama model, then try again."
)

ACTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_session",
            "description": "Start tracking a new work session (start a timer). Use when the user asks to start or begin working on something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "What they are working on"},
                    "issue_key": {"type": "string", "description": "Jira issue key like PAY-431, if known"},
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_worklog",
            "description": "Log time against a Jira ticket (add a worklog). Use when the user asks to log or record time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string"},
                    "minutes": {"type": "integer", "description": "Minutes of work to log"},
                    "comment": {"type": "string"},
                },
                "required": ["issue_key", "minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transition_ticket",
            "description": "Move a Jira ticket to a different status or column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string"},
                    "target": {"type": "string", "description": "Target status name, e.g. In Review or Done"},
                },
                "required": ["issue_key", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_day_plan",
            "description": "Save or update the user's plan/intention for today.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string"},
                    "ticket_keys": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_done",
            "description": "Mark a Jira ticket as Done (walks its workflow to Done; fails if subtasks are incomplete).",
            "parameters": {
                "type": "object",
                "properties": {"issue_key": {"type": "string"}},
                "required": ["issue_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_subtask",
            "description": "Create a sub-task under a parent Jira ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_key": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["parent_key", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_due_date",
            "description": "Set or change a Jira ticket's due date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["issue_key", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_priority",
            "description": "Change a Jira ticket's priority (e.g. High, Medium, Low).",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string"},
                    "priority": {"type": "string", "description": "Priority name"},
                },
                "required": ["issue_key", "priority"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reassign",
            "description": "Assign a Jira ticket to someone by name, or to nobody (unassign).",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string"},
                    "assignee": {"type": "string", "description": "Display name, or 'me', or 'nobody' to unassign"},
                },
                "required": ["issue_key", "assignee"],
            },
        },
    },
]

READ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_my_tickets",
            "description": "List Jira tickets assigned to the user, optionally filtered by urgency. Use to answer questions about what's assigned/overdue/due today/due soon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urgency": {
                        "type": "string",
                        "enum": ["all", "overdue", "due_today", "due_soon"],
                        "description": "Filter; default all",
                    },
                    "limit": {"type": "integer", "description": "Max to return (default 50)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticket",
            "description": "Full details of one Jira ticket: status, assignee, priority, dates, subtasks, and available transitions.",
            "parameters": {
                "type": "object",
                "properties": {"issue_key": {"type": "string"}},
                "required": ["issue_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticket_worklogs",
            "description": "The worklogs (logged time entries) on a Jira ticket.",
            "parameters": {
                "type": "object",
                "properties": {"issue_key": {"type": "string"}},
                "required": ["issue_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_day_summary",
            "description": "The user's tracked work sessions for today: total time and a per-ticket breakdown.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_sessions",
            "description": "The user's most recent work sessions (any day), with ticket, duration and state.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Default 15"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_week_report",
            "description": "This week's tracked-vs-logged totals, per day and per ticket.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan_today",
            "description": "A ranked plan of the user's tickets fitted to a capacity, with per-ticket time estimates from learned velocity.",
            "parameters": {
                "type": "object",
                "properties": {"capacity_hours": {"type": "number", "description": "Default 6"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_velocity",
            "description": "The user's learned typical time per issue type (from their history).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_activity",
            "description": "The user's git commits today (or since the session start) from their configured local repos. Pass issue_key to get commits on that ticket's repo; omit it for all repos. Use this to draft worklog comments from real commits.",
            "parameters": {
                "type": "object",
                "properties": {"issue_key": {"type": "string"}},
            },
        },
    },
]

ASSISTANT_TOOLS = ACTION_TOOLS + READ_TOOLS
READ_TOOL_NAMES = {t["function"]["name"] for t in READ_TOOLS}


def _fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, m = seconds // 3600, (seconds % 3600) // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


# --------------------------------------------------------------------------
# Context snapshot (cheap grounding; the model uses tools for anything deeper)
# --------------------------------------------------------------------------

def _pin_local_day(db: Session, req: AssistantChatRequest) -> None:
    """Make "today" follow the configured timezone, not the client's clock."""
    tz = app_tz(db)
    today = local_today(tz)
    start, _ = day_bounds(today, today, tz)
    req.local_date = today.isoformat()
    req.day_start = start
    req.day_end = datetime.now(timezone.utc)


def build_context_text(db: Session, req: AssistantChatRequest) -> str:
    now = datetime.now(timezone.utc)
    lines: list[str] = []
    local_now = now.astimezone(app_tz(db))
    lines.append(f"- Local time: {local_now.strftime('%Y-%m-%d %H:%M')} ({local_now.tzname()})")
    if req.local_date:
        lines.append(f"- Local date: {req.local_date}")

    active = (
        db.execute(
            select(WorkSession)
            .where(WorkSession.state.in_(("active", "paused")))
            .order_by(WorkSession.started_at.desc())
        )
        .scalars()
        .first()
    )
    if active:
        elapsed = live_elapsed_seconds(
            active.started_at, now, active.paused_seconds, active.state,
            getattr(active, "paused_at", None),
        )
        key = active.issue_key or "(no ticket)"
        lines.append(
            f'- Active session: {key} "{active.description}", running '
            f"{_fmt_hms(elapsed)} (state {active.state})"
        )
    else:
        lines.append("- Active session: none (not currently tracking)")

    if req.day_start and req.day_end:
        per, total = _sessions_breakdown(db, req.day_start, req.day_end, now)
        lines.append(f"- Today: {len(per)} tickets worked, {_fmt_hms(total)} tracked")
        for k, v in sorted(per.items(), key=lambda x: -x[1])[:6]:
            lines.append(f"    - {k}: {_fmt_hms(v)}")

    if req.local_date:
        intent = db.query(DayIntention).filter_by(plan_date=req.local_date).one_or_none()
        if intent and (intent.note or intent.ticket_keys):
            keys = f" [{', '.join(intent.ticket_keys)}]" if intent.ticket_keys else ""
            lines.append(f"- Today's plan (their intention): {intent.note}{keys}")
        else:
            lines.append("- Today's plan: not set yet")

    # Ticket counts only (details are one list_my_tickets tool-call away).
    try:
        with build_client(db) as client:
            tickets = get_my_tickets(client, tz=app_tz(db))
        c = {"overdue": 0, "due_today": 0, "due_soon": 0}
        for t in tickets:
            if t.urgency in c:
                c[t.urgency] += 1
        lines.append(
            f"- My tickets: {c['overdue']} overdue, {c['due_today']} due today, "
            f"{c['due_soon']} due soon, {len(tickets)} total assigned. "
            "Call list_my_tickets or get_ticket for details."
        )
    except Exception:  # noqa: BLE001 - Jira optional
        lines.append("- My tickets: unavailable (not connected to Jira right now)")

    return "CONTEXT (the user's real current data; ground answers in this, and call tools to fetch more):\n" + "\n".join(lines)


def _sessions_breakdown(db, start, end, now) -> tuple[dict[str, int], int]:
    rows = (
        db.execute(
            select(WorkSession).where(
                WorkSession.started_at >= start, WorkSession.started_at <= end
            )
        )
        .scalars()
        .all()
    )
    per: dict[str, int] = {}
    total = 0
    for s in rows:
        secs = effective_duration_seconds(
            s.started_at, s.ended_at or now, s.paused_seconds, s.adjusted_seconds
        )
        total += secs
        k = s.issue_key or "(no ticket)"
        per[k] = per.get(k, 0) + secs
    return per, total


# --------------------------------------------------------------------------
# Read-tool execution (returns a JSON string fed back to the model)
# --------------------------------------------------------------------------

def _json(obj) -> str:
    return json.dumps(obj, default=str)


def run_read_tool(name: str, args: dict, db: Session, req: AssistantChatRequest) -> str:
    now = datetime.now(timezone.utc)
    try:
        if name == "list_my_tickets":
            urgency = (args.get("urgency") or "all").lower()
            limit = int(args.get("limit") or 50)
            with build_client(db) as client:
                tickets = get_my_tickets(client, tz=app_tz(db))
            if urgency != "all":
                tickets = [t for t in tickets if t.urgency == urgency]
            return _json([asdict(t) for t in tickets[:limit]])

        if name == "get_ticket":
            with build_client(db) as client:
                return _json(asdict(get_manage_view(client, str(args["issue_key"]))))

        if name == "get_ticket_worklogs":
            with build_client(db) as client:
                return _json(list_worklogs(client, str(args["issue_key"])))

        if name == "get_day_summary":
            start = req.day_start
            end = req.day_end or now
            if start is None:
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            per, total = _sessions_breakdown(db, start, end, now)
            return _json({"total_seconds": total, "by_ticket": per})

        if name == "list_recent_sessions":
            limit = int(args.get("limit") or 15)
            rows = (
                db.execute(
                    select(WorkSession).order_by(WorkSession.started_at.desc()).limit(limit)
                )
                .scalars()
                .all()
            )
            out = []
            for s in rows:
                dur = effective_duration_seconds(
                    s.started_at, s.ended_at or now, s.paused_seconds, s.adjusted_seconds
                )
                out.append({
                    "issue_key": s.issue_key,
                    "description": s.description,
                    "state": s.state,
                    "started_at": s.started_at,
                    "duration_seconds": dur,
                })
            return _json(out)

        if name == "get_week_report":
            return _json(asdict(week_report(db)))

        if name == "get_plan_today":
            cap = float(args.get("capacity_hours") or 6)
            with build_client(db) as client:
                plan = build_day_plan(db, client, capacity_hours=cap)
            return _json({
                "capacity_seconds": plan.capacity_seconds,
                "planned_seconds": plan.planned_seconds,
                "fitted_count": plan.fitted_count,
                "items": [
                    {
                        "issue_key": i.ticket.issue_key,
                        "summary": i.ticket.summary,
                        "estimate_seconds": i.estimate_seconds,
                        "fits": i.fits,
                    }
                    for i in plan.items
                ],
            })

        if name == "get_velocity":
            vel = compute_velocity(db)
            return _json({
                "total_samples": vel.total_samples,
                "overall_median_seconds": vel.overall_median_seconds,
                "by_type": {
                    k: {"median_seconds": v.median_seconds, "sample_count": v.sample_count}
                    for k, v in vel.by_type.items()
                },
            })

        if name == "get_git_activity":
            paths = get_settings().git_repo_paths
            if not paths:
                return _json({"error": "no git repos configured in settings"})
            since = req.day_start.isoformat() if req.day_start else (now - timedelta(hours=24)).isoformat()
            key = args.get("issue_key")
            if key:
                repo = find_repo_for_issue(paths, str(key))
                if not repo:
                    return _json({"issue_key": key, "commits": [], "note": "no local repo whose branch matches this key"})
                return _json({"issue_key": key, "repo": repo, "commits": commits_since(repo, since)})
            by_repo = {}
            for p in paths:
                try:
                    by_repo[p] = commits_since(p, since)
                except Exception:  # noqa: BLE001
                    by_repo[p] = []
            return _json({"since": since, "by_repo": by_repo})

        return _json({"error": f"unknown tool {name}"})
    except Exception as exc:  # noqa: BLE001 - a bad tool call must not break chat
        logger.warning("read tool %s failed: %s", name, exc)
        return _json({"error": str(exc)})


def _summary_for(name: str, args: dict) -> str:
    if name == "start_session":
        key = args.get("issue_key")
        desc = args.get("description") or "a new session"
        return f"Start a timer on {key + ': ' if key else ''}{desc}".strip()
    if name == "log_worklog":
        base = f"Log {args.get('minutes')}m on {args.get('issue_key')}"
        return base + (f": {args['comment']}" if args.get("comment") else "")
    if name == "transition_ticket":
        return f"Move {args.get('issue_key')} to {args.get('target')}"
    if name == "set_day_plan":
        return f"Set today's plan: {args.get('note', '')}"
    if name == "mark_done":
        return f"Mark {args.get('issue_key')} as Done"
    if name == "create_subtask":
        return f"Add subtask under {args.get('parent_key')}: {args.get('summary')}"
    if name == "set_due_date":
        return f"Set {args.get('issue_key')} due date to {args.get('date')}"
    if name == "set_priority":
        return f"Set {args.get('issue_key')} priority to {args.get('priority')}"
    if name == "reassign":
        return f"Assign {args.get('issue_key')} to {args.get('assignee')}"
    return name


def _proposed(tc: ToolCall) -> ProposedAction:
    return ProposedAction(type=tc.name, args=tc.arguments, summary=_summary_for(tc.name, tc.arguments))


def execute_action(db: Session, atype: str, args: dict, local_date: str | None = None) -> dict:
    """Run a confirmed action server-side. Returns {ok, message, session_id?}.
    Never raises: any failure comes back as {ok: False, message}.
    """
    a = args or {}
    try:
        if atype == "start_session":
            s = WorkSession(
                description=str(a.get("description") or "Work session"),
                board_id=None, started_at=utcnow(), state="active", paused_seconds=0,
            )
            db.add(s); db.commit(); db.refresh(s)
            key = a.get("issue_key")
            if key:
                s.issue_key = str(key); s.issue_origin = "manual"; db.commit(); db.refresh(s)
            return {"ok": True, "session_id": s.id,
                    "message": "Started a timer" + (f" on {key}" if key else "") + "."}

        if atype == "set_day_plan":
            plan_date = local_date or local_today(app_tz(db)).isoformat()
            row = db.query(DayIntention).filter_by(plan_date=plan_date).one_or_none()
            if row is None:
                row = DayIntention(plan_date=plan_date); db.add(row)
            row.note = str(a.get("note") or "")
            row.ticket_keys = [str(k) for k in (a.get("ticket_keys") or [])]
            db.commit()
            return {"ok": True, "message": "Saved today's plan."}

        # The rest talk to Jira.
        settings = db.get(AppSettings, 1)
        account_id = settings.account_id if settings else None
        with build_client(db) as client:
            if atype == "log_worklog":
                log_work(client, str(a["issue_key"]), hours=0, minutes=int(a.get("minutes") or 0),
                         started=None, comment=(str(a["comment"]) if a.get("comment") else None),
                         account_id=account_id)
                return {"ok": True, "message": f"Logged {a.get('minutes')}m on {a.get('issue_key')}."}
            if atype == "transition_ticket":
                walk_to_status(client, str(a["issue_key"]), str(a["target"]))
                return {"ok": True, "message": f"Moved {a['issue_key']} to {a['target']}."}
            if atype == "mark_done":
                mark_done(client, str(a["issue_key"]))
                return {"ok": True, "message": f"Marked {a['issue_key']} as Done."}
            if atype == "create_subtask":
                sub = create_subtask(db, client, str(a["parent_key"]), str(a["summary"]))
                return {"ok": True, "message": f"Created subtask {sub} under {a['parent_key']}."}
            if atype == "set_due_date":
                edit_dates(client, str(a["issue_key"]), {"duedate": str(a["date"])})
                return {"ok": True, "message": f"Set {a['issue_key']} due {a['date']}."}
            if atype == "set_priority":
                want = str(a.get("priority") or "").strip().lower()
                prios = list_priorities(client)
                match = next((p for p in prios if want and want in (p.get("name") or "").lower()), None)
                if not match:
                    names = ", ".join(p.get("name") for p in prios if p.get("name"))
                    return {"ok": False, "message": f"No priority matching '{a.get('priority')}'. Options: {names}."}
                set_priority(client, str(a["issue_key"]), match["id"])
                return {"ok": True, "message": f"Set {a['issue_key']} priority to {match.get('name')}."}
            if atype == "reassign":
                who = str(a.get("assignee") or "").strip()
                key = str(a["issue_key"])
                if who.lower() in ("nobody", "none", "unassigned", "unassign"):
                    set_assignee(client, key, None)
                    return {"ok": True, "message": f"Unassigned {key}."}
                users = search_assignable_users(client, key, "" if who.lower() == "me" else who)
                if who.lower() == "me" and account_id:
                    users = [u for u in users if u.get("account_id") == account_id] or users
                if not users:
                    return {"ok": False, "message": f"No assignable user matching '{who}'."}
                u = users[0]
                set_assignee(client, key, u["account_id"])
                return {"ok": True, "message": f"Assigned {key} to {u.get('display_name')}."}

        return {"ok": False, "message": f"Unknown action {atype}."}
    except Exception as exc:  # noqa: BLE001 - surface, never crash
        logger.warning("execute_action %s failed: %s", atype, exc)
        return {"ok": False, "message": str(exc) or "Action failed."}


# --------------------------------------------------------------------------
# Agentic chat loop
# --------------------------------------------------------------------------

def run_chat(db: Session, req: AssistantChatRequest) -> AssistantChatResponse:
    _pin_local_day(db, req)
    system = ASSISTANT_SYSTEM + "\n\n" + build_context_text(db, req)
    messages: list[dict] = [{"role": "system", "content": system}]
    for m in req.messages[-12:]:
        content = (m.content or "").strip()
        if content:
            messages.append({"role": "assistant" if m.role == "assistant" else "user", "content": content})

    last_text = ""
    for _ in range(MAX_ITERS):
        result = safe_chat(db, messages, ASSISTANT_TOOLS)
        if not result.used_ai:
            # If we already produced text in an earlier round, keep it.
            return AssistantChatResponse(reply=last_text or UNAVAILABLE, used_ai=bool(last_text), action=None)
        last_text = result.text or last_text

        # A write tool-call stops the loop and asks the user to confirm.
        writes = [tc for tc in result.tool_calls if tc.name in ACTION_TYPES]
        if writes:
            action = _proposed(writes[0])
            reply = result.text or f"I can do that: {action.summary}. Confirm below to run it."
            return AssistantChatResponse(reply=reply, used_ai=True, action=action)

        reads = [tc for tc in result.tool_calls if tc.name in READ_TOOL_NAMES]
        if reads:
            # Echo the assistant's tool-call message, then answer each call by id.
            if result.raw_message is not None:
                messages.append(result.raw_message)
            for tc in reads:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": run_read_tool(tc.name, tc.arguments, db, req),
                })
            continue  # loop back so the model can use the results

        # No tool calls: final answer.
        return AssistantChatResponse(reply=result.text or "How can I help with your work?", used_ai=True, action=None)

    # Loop budget exhausted.
    return AssistantChatResponse(
        reply=last_text or "I gathered a lot of data but ran out of steps. Try narrowing the question.",
        used_ai=True,
        action=None,
    )
