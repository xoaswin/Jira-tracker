// End-of-day nudge (section 11). An in-app banner shown once past the configured
// nudge time when there are completed sessions not yet logged to Jira. Dismissible
// for the current session; reappears next load if work is still unlogged.

import { useEffect, useRef, useState } from "react";
import { BellRing, X } from "lucide-react";
import { useSettings, useUnlogged } from "../api/hooks";
import { isPastNudgeTime } from "../lib/idle";
import { useUi } from "../store/ui";

export function NudgeBanner() {
  const settings = useSettings();
  const unlogged = useUnlogged();
  const { setScreen } = useUi();
  const [dismissed, setDismissed] = useState(false);
  const notified = useRef(false);

  const count = unlogged.data?.length ?? 0;
  const past = isPastNudgeTime(settings.data?.nudge_time);
  const showing = !dismissed && count > 0 && past;

  // Fire a desktop notification once per app load when the nudge first shows.
  // Requests permission lazily; degrades silently if denied or unsupported.
  useEffect(() => {
    if (!showing || notified.current) return;
    if (typeof Notification === "undefined") return;
    notified.current = true;

    const fire = () => {
      try {
        new Notification("Work Session Tracker", {
          body: `You have ${count} session${count > 1 ? "s" : ""} not logged to Jira yet.`,
        });
      } catch {
        /* some browsers require a user gesture; the in-app banner still shows */
      }
    };
    if (Notification.permission === "granted") fire();
    else if (Notification.permission !== "denied") {
      Notification.requestPermission().then((p) => {
        if (p === "granted") fire();
      });
    }
  }, [showing, count]);

  if (!showing) return null;

  return (
    <div className="border-b border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950">
      <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-2 text-sm text-amber-900 dark:text-amber-200">
        <BellRing className="h-4 w-4 shrink-0" />
        <span className="flex-1">
          End of day: you have {count} session{count > 1 ? "s" : ""} not logged to
          Jira yet.
        </span>
        <button
          className="font-medium underline"
          onClick={() => setScreen("dashboard")}
        >
          Review
        </button>
        <button onClick={() => setDismissed(true)} title="Dismiss">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
