// Daily completeness nudge: after your work day ends, if the time tracked today
// is short of your daily target, prompt you to account for the rest. For a 12-9
// day with a 1h break the target is 7.5h; fall below it and this asks "what
// else did you do?" and points you at logging it.
//
// Purely local-clock and local-timezone (see lib/idle + lib/gaps helpers).

import { useEffect, useRef, useState } from "react";
import { ClipboardCheck, X } from "lucide-react";
import { useSessions, useSettings } from "../api/hooks";
import { isPastWorkEnd } from "../lib/idle";
import { isLocalToday } from "../lib/gaps";
import { toHours } from "../lib/time";
import { useUi } from "../store/ui";

export function DailyCompletenessNudge() {
  const settings = useSettings();
  const sessions = useSessions();
  const { setScreen } = useUi();
  const [dismissed, setDismissed] = useState(false);
  const notified = useRef(false);

  const target = settings.data?.daily_target_hours ?? 0;
  const workEnd = settings.data?.work_end_time ?? null;

  // Tracked time today across every session that has run (any state that has
  // accrued elapsed time), so the number reflects real desk time, not just
  // completed-and-synced work.
  const nowMs = Date.now();
  const trackedSeconds = (sessions.data ?? [])
    .filter((s) => isLocalToday(s.started_at, nowMs))
    .reduce((sum, s) => sum + Math.max(0, s.elapsed_seconds ?? 0), 0);

  const trackedHours = toHours(trackedSeconds);
  const past = isPastWorkEnd(workEnd, new Date(nowMs));
  // Only nudge when a target is set, we're past work end, and we're short.
  const short = target > 0 && past && trackedHours < target;
  const showing = short && !dismissed;

  useEffect(() => {
    if (!showing || notified.current) return;
    if (typeof Notification === "undefined") return;
    notified.current = true;
    const fire = () => {
      try {
        new Notification("Work Session Tracker", {
          body: `You've tracked ${trackedHours}h of ${target}h today. What else did you work on?`,
        });
      } catch {
        /* in-app banner still shows */
      }
    };
    if (Notification.permission === "granted") fire();
    else if (Notification.permission !== "denied") {
      Notification.requestPermission().then((p) => p === "granted" && fire());
    }
  }, [showing, trackedHours, target]);

  if (!showing) return null;

  const remaining = Math.max(0, Math.round((target - trackedHours) * 10) / 10);

  return (
    <div className="border-b border-indigo-300 bg-indigo-50 dark:border-indigo-800 dark:bg-indigo-950">
      <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-2 text-sm text-indigo-900 dark:text-indigo-200">
        <ClipboardCheck className="h-4 w-4 shrink-0" />
        <span className="flex-1">
          You've tracked <strong>{trackedHours}h</strong> of your {target}h target
          today, {remaining}h short. What else did you work on?
        </span>
        <button
          className="font-medium underline"
          onClick={() => setScreen("dashboard")}
        >
          Log it
        </button>
        <button onClick={() => setDismissed(true)} title="Dismiss">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
