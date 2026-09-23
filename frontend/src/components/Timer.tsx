// A live-ticking clock for the active session.

import { useEffect, useState } from "react";
import type { WorkSession } from "../api/types";
import { formatClock, sessionElapsedSeconds } from "../lib/time";

export function Timer({ session }: { session: WorkSession }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (session.state !== "active") return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [session.state]);

  // While paused the server snapshot is stable; while active we compute live.
  const seconds =
    session.state === "active"
      ? sessionElapsedSeconds(session)
      : (session.elapsed_seconds ?? sessionElapsedSeconds(session));

  const paused = session.state === "paused";

  return (
    <div className="text-center">
      <div
        className={`font-mono text-7xl font-bold tabular-nums tracking-tight ${
          paused ? "text-slate-400 dark:text-slate-500" : "text-slate-900 dark:text-white"
        }`}
      >
        {formatClock(seconds)}
      </div>
      <div className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-slate-400">
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            paused ? "bg-amber-400" : "animate-pulse bg-emerald-500"
          }`}
        />
        {paused ? "Paused" : "Tracking"}
      </div>
    </div>
  );
}
