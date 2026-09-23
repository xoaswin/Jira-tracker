import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Copy,
  Plus,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import {
  useDailySummary,
  useRetryAllOutbox,
  useSessions,
  useUnlogged,
  useWeekReport,
} from "../api/hooks";
import type { WorkSession } from "../api/types";
import { useUi } from "../store/ui";
import { formatDuration, toHours } from "../lib/time";
import { Banner, Button, Card, Spinner, TextArea } from "../components/ui";
import { WeekChart } from "../components/WeekChart";
import { EditableSession } from "../components/EditableSession";
import { ManualEntry } from "../components/ManualEntry";
import { GapDetection } from "../components/GapDetection";
import { SessionHistory } from "../components/SessionHistory";

function isToday(iso: string): boolean {
  const d = new Date(iso);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

function SyncBadge({ s }: { s: WorkSession }) {
  if (s.state !== "completed") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-slate-400">
        <Clock className="h-3.5 w-3.5" /> {s.state}
      </span>
    );
  }
  if (s.sync_state === "synced") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-500">
        <CheckCircle2 className="h-3.5 w-3.5" /> synced
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-amber-500">
      <AlertTriangle className="h-3.5 w-3.5" /> {s.sync_state}
    </span>
  );
}

function SessionRow({ s, editable = false }: { s: WorkSession; editable?: boolean }) {
  return (
    <li className="border-b border-slate-100 py-2 last:border-0 dark:border-slate-800">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm">
            {s.issue_key && (
              <span className="mr-2 font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                {s.issue_key}
              </span>
            )}
            {s.description}
          </p>
          {s.sync_error && (
            <p className="truncate text-xs text-rose-500">{s.sync_error}</p>
          )}
          {editable && s.state === "completed" && <EditableSession session={s} />}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="font-mono text-xs text-slate-500">
            {formatDuration(s.elapsed_seconds ?? 0)}
          </span>
          <SyncBadge s={s} />
        </div>
      </div>
    </li>
  );
}

export function Dashboard() {
  const sessions = useSessions();
  const week = useWeekReport();
  const unlogged = useUnlogged();
  const retryAll = useRetryAllOutbox();
  const { setScreen, reset } = useUi();

  if (sessions.isLoading) return <Spinner />;
  const all = sessions.data ?? [];
  const today = all.filter((s) => isToday(s.started_at));
  const needsAttention = unlogged.data ?? [];

  const trackedToday = today
    .filter((s) => s.state === "completed")
    .reduce((sum, s) => sum + (s.elapsed_seconds ?? 0), 0);
  const loggedToday = today
    .filter((s) => s.state === "completed" && s.sync_state === "synced")
    .reduce((sum, s) => sum + (s.elapsed_seconds ?? 0), 0);

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <Button
          onClick={() => {
            reset();
            setScreen("start");
          }}
        >
          <Plus className="h-4 w-4" />
          New session
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <p className="text-xs uppercase tracking-wide text-slate-400">
            Tracked today
          </p>
          <p className="mt-1 text-2xl font-semibold">{toHours(trackedToday)}h</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-slate-400">
            Logged to Jira today
          </p>
          <p className="mt-1 text-2xl font-semibold">{toHours(loggedToday)}h</p>
        </Card>
      </div>

      {/* Unaccounted time: stretches of today no session covers, one click to log. */}
      <GapDetection sessions={all} />

      {/* Standup summary: roll up today's completed sessions (AI-polished when
          available, plain otherwise). */}
      <StandupSummary />

      {/* Manual time entry: log past work without a live timer. */}
      <ManualEntry />

      {/* This week: tracked vs logged (section 11). */}
      {week.data && (
        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
              This week
            </h2>
            <span className="text-xs text-slate-400">
              {toHours(week.data.total_logged_seconds)}h logged of{" "}
              {toHours(week.data.total_tracked_seconds)}h tracked
            </span>
          </div>
          <WeekChart report={week.data} />
        </Card>
      )}

      {/* Unlogged sessions needing attention, with a retry (rule 2). */}
      {needsAttention.length > 0 && (
        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-4 w-4" />
              Needs attention ({needsAttention.length})
            </h2>
            <Button
              variant="secondary"
              loading={retryAll.isPending}
              onClick={() => retryAll.mutate()}
            >
              <RefreshCw className="h-4 w-4" />
              Retry all
            </Button>
          </div>
          <ul>
            {needsAttention.map((s) => (
              <SessionRow key={s.id} s={s} editable />
            ))}
          </ul>
          {retryAll.data?.reason === "not_connected" && (
            <Banner tone="info">
              Connect to Jira on the Settings screen to sync these.
            </Banner>
          )}
          {retryAll.data?.reason === "needs_reauth" && (
            <Banner tone="warning">
              Your Jira token needs reauthentication. Reconnect on Settings.
            </Banner>
          )}
        </Card>
      )}

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          Today's sessions
        </h2>
        {today.length === 0 ? (
          <p className="py-4 text-center text-sm text-slate-400">
            Nothing tracked today yet.
          </p>
        ) : (
          <ul>
            {today.map((s) => (
              <SessionRow key={s.id} s={s} />
            ))}
          </ul>
        )}
      </Card>

      {/* Look back at any past day's sessions. */}
      <SessionHistory />
    </div>
  );
}

// Standup summary: on click, roll up today's completed sessions into a short
// paragraph. AI-polished when a provider is configured and reachable; otherwise
// the backend returns a plain roll-up (used_ai = false) and we say so.
function StandupSummary() {
  const gen = useDailySummary();
  const [copied, setCopied] = useState(false);

  const text = gen.data?.text ?? "";

  function copy() {
    if (!text) return;
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <Sparkles className="h-4 w-4 text-indigo-500" />
          Standup summary
        </h2>
        <div className="flex items-center gap-2">
          {gen.data && (
            <Button variant="ghost" onClick={copy} title="Copy to clipboard">
              <Copy className="h-4 w-4" />
              {copied ? "Copied" : "Copy"}
            </Button>
          )}
          <Button
            variant="secondary"
            loading={gen.isPending}
            onClick={() => gen.mutate()}
          >
            <Sparkles className="h-4 w-4" />
            {gen.data ? "Regenerate" : "Generate"}
          </Button>
        </div>
      </div>

      {!gen.data && !gen.isPending && (
        <p className="text-sm text-slate-400">
          Summarize today's tracked work into a quick standup update.
        </p>
      )}

      {gen.data && (
        <>
          <TextArea
            rows={4}
            readOnly
            value={text}
            className="text-sm"
          />
          {!gen.data.used_ai && (
            <p className="text-xs text-slate-400">
              Plain roll-up (AI is off or unavailable). Enable a provider in
              Settings for a polished summary.
            </p>
          )}
        </>
      )}

      {gen.isError && (
        <Banner tone="error">{String(gen.error)}</Banner>
      )}
    </Card>
  );
}
