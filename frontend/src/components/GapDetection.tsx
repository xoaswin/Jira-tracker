// Gap detection: surface stretches of today's workday that no session covers,
// so forgotten time can be logged in one click. Pure client-side analysis (see
// lib/gaps) over the sessions the Dashboard already has.

import { useMemo, useState } from "react";
import { Check, Clock3, X } from "lucide-react";
import { useManualSession } from "../api/hooks";
import type { WorkSession } from "../api/types";
import { findGaps, formatClockTime, isLocalToday, type Gap } from "../lib/gaps";
import { formatDuration } from "../lib/time";
import { Banner, Button, Card, Label, TextInput } from "./ui";

// Default assumed workday. Kept local to the component; could move to settings.
const WORK_START_HOUR = 9;
const WORK_END_HOUR = 18;

export function GapDetection({ sessions }: { sessions: WorkSession[] }) {
  // Only today's sessions feed the analysis; recompute when they change.
  const gaps = useMemo(() => {
    const nowMs = Date.now();
    const todays = sessions.filter((s) => isLocalToday(s.started_at, nowMs));
    return findGaps(
      todays.map((s) => ({
        started_at: s.started_at,
        elapsed_seconds: s.elapsed_seconds,
        state: s.state,
      })),
      { startHour: WORK_START_HOUR, endHour: WORK_END_HOUR, nowMs },
    );
  }, [sessions]);

  // Gaps the user has dismissed this session (not persisted; a light "not now").
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const visible = gaps.filter((g) => !dismissed.has(g.startMs));

  if (visible.length === 0) return null;

  const totalSeconds = visible.reduce((sum, g) => sum + g.durationSeconds, 0);

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-600 dark:text-amber-400">
          <Clock3 className="h-4 w-4" />
          Unaccounted time ({formatDuration(totalSeconds)})
        </h2>
        <span className="text-xs text-slate-400">
          {WORK_START_HOUR}:00 to {WORK_END_HOUR}:00
        </span>
      </div>
      <p className="text-xs text-slate-400">
        These stretches of today aren't covered by any session. Log the ones
        that were real work.
      </p>
      <ul className="space-y-2">
        {visible.map((g) => (
          <GapRow
            key={g.startMs}
            gap={g}
            onDismiss={() =>
              setDismissed((prev) => new Set(prev).add(g.startMs))
            }
          />
        ))}
      </ul>
    </Card>
  );
}

function GapRow({ gap, onDismiss }: { gap: Gap; onDismiss: () => void }) {
  const manual = useManualSession();
  const [expanded, setExpanded] = useState(false);
  const [description, setDescription] = useState("");
  const [issueKey, setIssueKey] = useState("");
  const [done, setDone] = useState(false);

  const range = `${formatClockTime(gap.startMs)} – ${formatClockTime(gap.endMs)}`;
  const canLog = description.trim().length > 0;

  function log() {
    if (!canLog) return;
    manual.mutate(
      {
        description: description.trim(),
        duration_seconds: gap.durationSeconds,
        issue_key: issueKey.trim() || null,
        // The gap's real start instant, as an absolute timestamp.
        started_at: new Date(gap.startMs).toISOString(),
      },
      {
        onSuccess: () => {
          setDone(true);
          window.setTimeout(onDismiss, 1200);
        },
      },
    );
  }

  return (
    <li className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {range}
          </span>
          <span className="ml-2 text-xs text-slate-400">
            {formatDuration(gap.durationSeconds)}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {done ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-500">
              <Check className="h-3.5 w-3.5" />
              Logged
            </span>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setExpanded((v) => !v)}>
                {expanded ? "Cancel" : "Log this"}
              </Button>
              <button
                onClick={onDismiss}
                title="Dismiss"
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-rose-500 dark:hover:bg-slate-800"
              >
                <X className="h-4 w-4" />
              </button>
            </>
          )}
        </div>
      </div>

      {expanded && !done && (
        <div className="mt-3 space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <Label>What was this?</Label>
              <TextInput
                autoFocus
                placeholder="e.g. code review, incident call"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div>
              <Label>Ticket (optional)</Label>
              <TextInput
                placeholder="e.g. PAY-431"
                value={issueKey}
                onChange={(e) => setIssueKey(e.target.value.toUpperCase())}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={log} loading={manual.isPending} disabled={!canLog}>
              <Check className="h-4 w-4" />
              Log {formatDuration(gap.durationSeconds)}
            </Button>
            {!issueKey.trim() && (
              <span className="text-xs text-slate-400">
                No ticket: tracked locally only.
              </span>
            )}
          </div>
          {manual.isError && <Banner tone="error">{String(manual.error)}</Banner>}
        </div>
      )}
    </li>
  );
}
