// Weekly tracked-vs-logged bar chart (section 11). Pure CSS bars, no chart lib.
// Each day shows tracked hours (light) with the logged portion (solid) overlaid,
// so the gap between the two is the unlogged time at a glance.

import type { WeekReport } from "../api/types";
import { toHours } from "../lib/time";

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function WeekChart({ report }: { report: WeekReport }) {
  const maxSeconds = Math.max(
    1,
    ...report.days.map((d) => d.tracked_seconds),
  );

  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-2" style={{ height: 140 }}>
        {report.days.map((d, i) => {
          const trackedPct = (d.tracked_seconds / maxSeconds) * 100;
          const loggedPct = (d.logged_seconds / maxSeconds) * 100;
          return (
            <div key={d.day} className="flex flex-1 flex-col items-center justify-end gap-1">
              <div
                className="relative flex w-full items-end justify-center rounded-t bg-slate-100 dark:bg-slate-800"
                style={{ height: `${Math.max(trackedPct, 2)}%` }}
                title={`${toHours(d.tracked_seconds)}h tracked, ${toHours(
                  d.logged_seconds,
                )}h logged`}
              >
                <div
                  className="absolute bottom-0 w-full rounded-t bg-indigo-500"
                  style={{
                    height: d.tracked_seconds
                      ? `${(loggedPct / trackedPct) * 100}%`
                      : "0%",
                  }}
                />
              </div>
              <span className="text-[10px] text-slate-400">{DAY_LABELS[i]}</span>
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-center gap-4 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm bg-indigo-500" /> logged
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm bg-slate-200 dark:bg-slate-700" /> tracked
        </span>
      </div>
    </div>
  );
}
