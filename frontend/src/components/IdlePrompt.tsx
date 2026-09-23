// Idle prompt (section 11). When the user returns after being idle longer than
// the configured threshold during an active session, ask whether to keep the
// idle time or subtract it. Subtracting sets adjusted_seconds on the session to
// the tracked elapsed minus the idle span.

import { Coffee } from "lucide-react";
import { useActiveSession, useSettings, useUpdateSession } from "../api/hooks";
import { useIdleDetection } from "../lib/idle";
import { Button } from "./ui";

export function IdlePrompt() {
  const settings = useSettings();
  const active = useActiveSession();
  const updateSession = useUpdateSession();

  const threshold = settings.data?.idle_threshold_minutes ?? 15;
  // Only detect while there is a running (not paused) session.
  const enabled = active.data?.state === "active";
  const { idleMinutes, clearIdle } = useIdleDetection(threshold, enabled);

  if (idleMinutes == null || !active.data) return null;

  const session = active.data;
  const idleSeconds = idleMinutes * 60;

  function keep() {
    clearIdle();
  }

  function subtract() {
    const elapsed = session.elapsed_seconds ?? 0;
    const adjusted = Math.max(0, elapsed - idleSeconds);
    updateSession.mutate(
      { id: session.id, patch: { adjusted_seconds: adjusted } },
      { onSettled: () => clearIdle() },
    );
  }

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-3">
          <Coffee className="h-6 w-6 text-amber-500" />
          <h2 className="text-lg font-semibold">Welcome back</h2>
        </div>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          You were idle for about {idleMinutes} minute{idleMinutes > 1 ? "s" : ""}.
          Keep that time on this session, or subtract it?
        </p>
        <div className="flex gap-3">
          <Button onClick={subtract} loading={updateSession.isPending}>
            Subtract {idleMinutes}m
          </Button>
          <Button variant="secondary" onClick={keep}>
            Keep it
          </Button>
        </div>
      </div>
    </div>
  );
}
