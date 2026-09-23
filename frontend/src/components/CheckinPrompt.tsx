// Recurring check-in: during your work hours, every N minutes, prompt to
// confirm what you're working on, so time is captured (or corrected) as it
// happens rather than reconstructed later. It fires whether or not a timer is
// running:
//
// * No active session -> "What are you working on?" with a Start tracking
//   button, so untracked stretches get captured.
// * Active session    -> "Still working on <TICKET>?" so a stale timer (you
//   moved on but forgot to switch) gets caught. "Yes" dismisses; "Switch"
//   jumps to Start to begin a new session.
//
// Purely local-clock and local-timezone (see lib/idle helpers).

import { useEffect, useRef, useState } from "react";
import { Check, HelpCircle, Play, RefreshCw } from "lucide-react";
import { useActiveSession, useSettings } from "../api/hooks";
import { isWithinWorkWindow } from "../lib/idle";
import { notifyDesktop } from "../lib/notify";
import { useUi } from "../store/ui";
import { Button } from "./ui";

// How often to re-evaluate whether a prompt is due. A minute is precise enough
// for an hourly cadence and cheap.
const TICK_MS = 60_000;

export function CheckinPrompt() {
  const settings = useSettings();
  const active = useActiveSession();
  const { setScreen, reset } = useUi();

  const [visible, setVisible] = useState(false);
  // Wall-clock time we last showed (or answered) a prompt, so the interval is
  // measured from the last interaction, not from app load.
  const lastPromptRef = useRef<number>(Date.now());

  const intervalMin = settings.data?.checkin_interval_minutes ?? 0;
  const workStart = settings.data?.work_start_time ?? null;
  const workEnd = settings.data?.work_end_time ?? null;
  const session = active.data;

  useEffect(() => {
    if (intervalMin <= 0) return;

    function evaluate() {
      if (visible) return;
      // Only within work hours. Unlike idle detection, we DO prompt during an
      // active session: the point is to confirm the timer still reflects
      // reality, not just to catch untracked gaps.
      if (!isWithinWorkWindow(workStart, workEnd)) return;
      const elapsedMin = (Date.now() - lastPromptRef.current) / 60000;
      if (elapsedMin < intervalMin) return;

      setVisible(true);
      // The in-page modal only gets seen if this tab is focused. Also fire a
      // native OS notification so the check-in surfaces even if you're
      // working in another window (no-op if not supported/permitted).
      const hasActive =
        session?.state === "active" || session?.state === "paused";
      notifyDesktop(
        hasActive ? "Still on this?" : "What are you working on?",
        hasActive
          ? `Tracking ${session?.issue_key ?? "a session"}${
              session?.description ? `: ${session.description}` : ""
            }`
          : "No timer is running. Click to log it before it's forgotten.",
      );
    }

    const first = window.setTimeout(evaluate, 2000);
    const interval = window.setInterval(evaluate, TICK_MS);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(interval);
    };
  }, [intervalMin, workStart, workEnd, visible, session]);

  if (!visible) return null;

  function answer() {
    // Any answer resets the interval clock and closes the prompt.
    lastPromptRef.current = Date.now();
    setVisible(false);
  }

  function goToStart() {
    answer();
    reset();
    setScreen("start");
  }

  const hasActive =
    session?.state === "active" || session?.state === "paused";

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-3">
          <HelpCircle className="h-6 w-6 text-indigo-500" />
          <h2 className="text-lg font-semibold">
            {hasActive ? "Still on this?" : "What are you working on?"}
          </h2>
        </div>

        {hasActive ? (
          <>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              You're tracking{" "}
              {session?.issue_key ? (
                <span className="font-mono font-semibold">{session.issue_key}</span>
              ) : (
                "a session"
              )}
              {session?.description ? `: ${session.description}` : ""}. Still what
              you're working on?
            </p>
            <div className="flex gap-3">
              <Button onClick={answer}>
                <Check className="h-4 w-4" />
                Yes, still on it
              </Button>
              <Button variant="secondary" onClick={goToStart}>
                <RefreshCw className="h-4 w-4" />
                Switch task
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              No timer is running. Start tracking what you're doing so it doesn't
              go unlogged.
            </p>
            <div className="flex gap-3">
              <Button onClick={goToStart}>
                <Play className="h-4 w-4" />
                Start tracking
              </Button>
              <Button variant="secondary" onClick={answer}>
                Snooze
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
