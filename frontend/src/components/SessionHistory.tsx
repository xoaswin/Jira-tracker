// Session history: look back at any past day's sessions, not just today. Uses
// the sessions list endpoint's from/to range filter. Local-day boundaries are
// converted to absolute ISO instants so the query matches the UTC-stored rows.

import { useState } from "react";
import { CalendarDays, History } from "lucide-react";
import { useSessionsInRange } from "../api/hooks";
import type { WorkSession } from "../api/types";
import { formatDuration, toHours } from "../lib/time";
import { formatClock, zonedDateStr, zonedWallToMs } from "../lib/tz";
import { Banner, Button, Card, Label, Spinner, TextInput } from "./ui";

// App-timezone start/end of a YYYY-MM-DD date, as ISO instants for the query.
function dayBounds(dateStr: string): { from: string; to: string } | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return null;
  const start = zonedWallToMs(dateStr);
  const end = zonedWallToMs(dateStr, 23, 59, 59, 999);
  return { from: new Date(start).toISOString(), to: new Date(end).toISOString() };
}

export function SessionHistory() {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(zonedDateStr());

  const bounds = dayBounds(date);
  const q = useSessionsInRange(
    open ? bounds?.from ?? null : null,
    open ? bounds?.to ?? null : null,
  );

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <History className="h-4 w-4" />
        Session history
      </Button>
    );
  }

  const sessions = q.data ?? [];
  const tracked = sessions
    .filter((s) => s.state === "completed")
    .reduce((sum, s) => sum + (s.elapsed_seconds ?? 0), 0);

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <History className="h-4 w-4 text-indigo-500" />
          Session history
        </h2>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>

      <div className="flex items-end gap-3">
        <div>
          <Label>Day</Label>
          <div className="relative">
            <CalendarDays className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <TextInput
              type="date"
              className="pl-9"
              value={date}
              max={zonedDateStr()}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
        </div>
        {sessions.length > 0 && (
          <p className="pb-2 text-sm text-slate-400">
            {toHours(tracked)}h tracked across {sessions.length} session
            {sessions.length === 1 ? "" : "s"}
          </p>
        )}
      </div>

      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="error">{String(q.error)}</Banner>}
      {q.data && sessions.length === 0 && (
        <p className="py-3 text-center text-sm text-slate-400">
          No sessions on {date}.
        </p>
      )}

      {sessions.length > 0 && (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {sessions.map((s) => (
            <HistoryRow key={s.id} s={s} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function HistoryRow({ s }: { s: WorkSession }) {
  const start = formatClock(s.started_at);
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-sm">
          {s.issue_key && (
            <span className="mr-2 font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
              {s.issue_key}
            </span>
          )}
          {s.description}
        </p>
        <p className="text-xs text-slate-400">
          {start} · {s.state}
          {s.state === "completed" && s.sync_state !== "synced"
            ? ` · ${s.sync_state}`
            : ""}
        </p>
      </div>
      <span className="shrink-0 font-mono text-xs text-slate-500">
        {formatDuration(s.elapsed_seconds ?? 0)}
      </span>
    </li>
  );
}
