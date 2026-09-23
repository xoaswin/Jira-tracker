// Mid-session budget: compares elapsed time against your learned estimate for
// this ticket's type, and warns when you go over. The estimate is the median
// actual time tickets of this type have taken you (see backend velocity); with
// no history it falls back to a rough default and says so.

import { useEffect, useState } from "react";
import { AlertTriangle, Gauge } from "lucide-react";
import { useEstimate } from "../api/hooks";
import type { WorkSession } from "../api/types";
import { formatDuration, sessionElapsedSeconds } from "../lib/time";

export function EstimateBudget({
  session,
  issueType,
}: {
  session: WorkSession;
  issueType: string | null;
}) {
  const est = useEstimate(issueType, !!session.issue_key);

  // Tick so the bar/warning update live while the timer runs.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (session.state !== "active") return;
    const id = setInterval(() => setTick((t) => t + 1), 5000);
    return () => clearInterval(id);
  }, [session.state]);

  if (!session.issue_key || !est.data) return null;

  const estimate = est.data.estimate_seconds;
  if (estimate <= 0) return null;

  const elapsed =
    session.state === "active"
      ? sessionElapsedSeconds(session)
      : (session.elapsed_seconds ?? sessionElapsedSeconds(session));

  const ratio = elapsed / estimate;
  const pct = Math.min(100, Math.round(ratio * 100));
  const over = elapsed > estimate;

  // Tone: green under 80%, amber 80-100%, rose over.
  const barTone = over
    ? "bg-rose-500"
    : ratio >= 0.8
      ? "bg-amber-500"
      : "bg-emerald-500";

  const rough = est.data.based_on !== "type";

  return (
    <div className="mx-auto max-w-xs space-y-1">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span className="inline-flex items-center gap-1">
          <Gauge className="h-3.5 w-3.5" />
          {formatDuration(elapsed)} of ~{formatDuration(estimate)}
          {rough ? " (rough)" : ""}
        </span>
        <span>{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
        <div
          className={`h-full ${barTone} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {over && (
        <p className="inline-flex items-center gap-1 text-xs font-medium text-rose-500">
          <AlertTriangle className="h-3.5 w-3.5" />
          Over your usual {formatDuration(estimate)} for a{" "}
          {issueType ?? "ticket"} by {formatDuration(elapsed - estimate)}.
        </p>
      )}
    </div>
  );
}
