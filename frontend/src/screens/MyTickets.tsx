// My Tickets: everything assigned to me, live from Jira, with the ones past
// their due date (or due today/soon) called out so nothing slips. Click a
// ticket to open it in the Manage screen.

import { useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CalendarDays,
  CheckCircle2,
  ExternalLink,
  Play,
  RefreshCw,
  Settings2,
} from "lucide-react";
import {
  useActiveSession,
  useAuthStatus,
  useCreateSession,
  useMyTickets,
  useUpdateSession,
} from "../api/hooks";
import { ApiError } from "../api/client";
import { useUi } from "../store/ui";
import type { MyTicket, Urgency } from "../api/types";
import { Banner, Button, Card, Spinner } from "../components/ui";
import { PlanMyDay } from "../components/PlanMyDay";

// Presentation per urgency bucket: label, ordering, and colour.
const URGENCY: Record<
  Urgency,
  { label: string; tone: string; order: number }
> = {
  overdue: {
    label: "Overdue",
    tone: "text-rose-600 dark:text-rose-400",
    order: 0,
  },
  due_today: {
    label: "Due today",
    tone: "text-amber-600 dark:text-amber-400",
    order: 1,
  },
  due_soon: {
    label: "Due soon",
    tone: "text-sky-600 dark:text-sky-400",
    order: 2,
  },
  scheduled: {
    label: "Scheduled",
    tone: "text-slate-500",
    order: 3,
  },
  no_due: {
    label: "No due date",
    tone: "text-slate-400",
    order: 4,
  },
};

const GROUP_ORDER: Urgency[] = [
  "overdue",
  "due_today",
  "due_soon",
  "scheduled",
  "no_due",
];

function dueLabel(t: MyTicket): string {
  if (!t.due_date) return "No due date";
  const d = new Date(t.due_date).toLocaleDateString();
  if (t.days_until_due == null) return d;
  if (t.days_until_due < 0) {
    const n = Math.abs(t.days_until_due);
    return `${d} · ${n} day${n === 1 ? "" : "s"} overdue`;
  }
  if (t.days_until_due === 0) return `${d} · today`;
  return `${d} · in ${t.days_until_due} day${t.days_until_due === 1 ? "" : "s"}`;
}

export function MyTickets() {
  const auth = useAuthStatus();
  const q = useMyTickets();
  const active = useActiveSession();
  const createSession = useCreateSession();
  const updateSession = useUpdateSession();
  const { openInManage, setScreen, setCurrentSession } = useUi();
  const baseUrl = auth.data?.base_url ?? null;

  // A timer is already running; starting another would replace it. We disable
  // the Start buttons and point the user at the active session instead.
  const hasActive = !!active.data;
  const starting = createSession.isPending || updateSession.isPending;
  // Which ticket's Start button was clicked (for the per-row spinner).
  const [startingKey, setStartingKey] = useState<string | null>(null);

  function startTimer(t: MyTicket) {
    if (hasActive || starting) return;
    setStartingKey(t.issue_key);
    createSession.mutate(
      { description: `Work on ${t.issue_key}: ${t.summary}`.trim(), board_id: null },
      {
        onSuccess: (session) => {
          updateSession.mutate(
            {
              id: session.id,
              patch: { issue_key: t.issue_key, issue_origin: "manual" },
            },
            {
              onSuccess: () => {
                setCurrentSession(session.id);
                setScreen("active");
              },
              onSettled: () => setStartingKey(null),
            },
          );
        },
        onError: () => setStartingKey(null),
      },
    );
  }

  const data = q.data;
  const attention = data ? data.overdue + data.due_today + data.due_soon : 0;

  // Group the flat, already-urgency-sorted list into buckets for display.
  const groups: Record<Urgency, MyTicket[]> = {
    overdue: [],
    due_today: [],
    due_soon: [],
    scheduled: [],
    no_due: [],
  };
  (data?.tickets ?? []).forEach((t) => groups[t.urgency].push(t));

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">My tickets</h1>
          <p className="mt-1 text-sm text-slate-500">
            Everything assigned to you, with anything past its due date flagged.
          </p>
        </div>
        <Button
          variant="secondary"
          loading={q.isFetching}
          onClick={() => q.refetch()}
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      {/* Plan my day: ranked + capacity-fitted, with learned estimates. */}
      <PlanMyDay />

      {/* Attention summary */}
      {data && (
        <div className="grid grid-cols-3 gap-4">
          <SummaryTile
            icon={<AlertTriangle className="h-4 w-4" />}
            label="Overdue"
            count={data.overdue}
            tone={data.overdue > 0 ? "text-rose-600 dark:text-rose-400" : "text-slate-400"}
          />
          <SummaryTile
            icon={<CalendarClock className="h-4 w-4" />}
            label="Due today"
            count={data.due_today}
            tone={data.due_today > 0 ? "text-amber-600 dark:text-amber-400" : "text-slate-400"}
          />
          <SummaryTile
            icon={<CalendarDays className="h-4 w-4" />}
            label="Due soon"
            count={data.due_soon}
            tone={data.due_soon > 0 ? "text-sky-600 dark:text-sky-400" : "text-slate-400"}
          />
        </div>
      )}

      {q.isLoading && <Spinner />}
      {q.isError && (
        <Banner tone="error">
          {q.error instanceof ApiError
            ? JSON.stringify(q.error.detail)
            : String(q.error)}
        </Banner>
      )}

      {data && data.tickets.length === 0 && (
        <Card>
          <p className="flex items-center justify-center gap-2 py-6 text-sm text-slate-400">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            Nothing assigned to you right now.
          </p>
        </Card>
      )}

      {data && attention === 0 && data.tickets.length > 0 && (
        <Banner tone="success">
          Nothing overdue or due soon — you're on top of it.
        </Banner>
      )}

      {/* Grouped list */}
      {GROUP_ORDER.map((u) =>
        groups[u].length === 0 ? null : (
          <div key={u} className="space-y-2">
            <h2 className={`text-sm font-semibold ${URGENCY[u].tone}`}>
              {URGENCY[u].label} ({groups[u].length})
            </h2>
            <Card className="divide-y divide-slate-100 p-0 dark:divide-slate-800">
              {groups[u].map((t) => (
                <TicketRow
                  key={t.issue_key}
                  ticket={t}
                  baseUrl={baseUrl}
                  onManage={() => openInManage(t.issue_key)}
                  onStart={() => startTimer(t)}
                  starting={startingKey === t.issue_key}
                  startDisabled={hasActive || starting}
                />
              ))}
            </Card>
          </div>
        ),
      )}
    </div>
  );
}

function SummaryTile({
  icon,
  label,
  count,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  tone: string;
}) {
  return (
    <Card>
      <p className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-slate-400">
        {icon}
        {label}
      </p>
      <p className={`mt-1 text-2xl font-semibold ${tone}`}>{count}</p>
    </Card>
  );
}

function TicketRow({
  ticket,
  baseUrl,
  onManage,
  onStart,
  starting,
  startDisabled,
}: {
  ticket: MyTicket;
  baseUrl: string | null;
  onManage: () => void;
  onStart: () => void;
  starting: boolean;
  startDisabled: boolean;
}) {
  const jiraUrl = baseUrl ? `${baseUrl}/browse/${ticket.issue_key}` : null;
  const overdue = ticket.urgency === "overdue";

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
            {ticket.issue_key}
          </span>
          {ticket.status && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500 dark:bg-slate-800">
              {ticket.status}
            </span>
          )}
          {ticket.priority && (
            <span className="text-[10px] text-slate-400">{ticket.priority}</span>
          )}
        </div>
        <p className="mt-0.5 truncate text-sm text-slate-800 dark:text-slate-200">
          {ticket.summary}
        </p>
        <p
          className={`mt-0.5 text-[11px] ${
            overdue ? "font-medium text-rose-500" : "text-slate-400"
          }`}
        >
          {dueLabel(ticket)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {jiraUrl && (
          <a
            href={jiraUrl}
            target="_blank"
            rel="noreferrer"
            title="Open in Jira"
            className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-indigo-600 dark:hover:bg-slate-800"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
        <Button
          variant="ghost"
          onClick={onStart}
          loading={starting}
          disabled={startDisabled}
          title={
            startDisabled
              ? "Finish the active session first"
              : "Start a timer on this ticket"
          }
        >
          <Play className="h-4 w-4" />
          Start
        </Button>
        <Button variant="ghost" onClick={onManage} title="Manage this ticket">
          <Settings2 className="h-4 w-4" />
          Manage
        </Button>
      </div>
    </div>
  );
}
