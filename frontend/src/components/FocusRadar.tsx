// Focus radar: last 7 days of deep work vs scattered activity, context
// switches and late hours, from the desktop activity recorder, plus plain
// suggestions. Headline numbers are stat tiles; the per-day chart stacks
// focus-block time under the rest of active time (one unit: hours).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain, Lightbulb } from "lucide-react";
import { api } from "../api/client";
import type { FocusDay } from "../api/types";
import { formatHm as formatDuration } from "../lib/time";
import { formatDateKey } from "../lib/tz";
import { Card, Spinner } from "./ui";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 px-3 py-2.5 dark:border-slate-800">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

export function FocusRadar() {
  const q = useQuery({ queryKey: ["activity-focus", 7], queryFn: () => api.activityFocus(7) });
  const [hover, setHover] = useState<FocusDay | null>(null);

  if (q.isLoading) return <Spinner />;
  const r = q.data;
  if (!r) return null;

  const days = r.days;
  const recorded = days.filter((d) => d.active_seconds > 0);
  const deep = recorded.reduce((n, d) => n + d.deep_seconds, 0);
  const active = recorded.reduce((n, d) => n + d.active_seconds, 0);
  const avgSwitches = recorded.length
    ? Math.round(recorded.reduce((n, d) => n + d.switches, 0) / recorded.length)
    : 0;
  const longest = Math.max(0, ...recorded.map((d) => d.longest_deep_seconds));
  const late = recorded.reduce((n, d) => n + d.late_seconds, 0);
  const max = Math.max(3600, ...days.map((d) => d.active_seconds));

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <Brain className="h-4 w-4" />
          Focus radar
        </h2>
        <span className="text-xs text-slate-400">Last 7 days</span>
      </div>

      {!r.recording ? (
        <p className="text-sm text-slate-500">
          Nothing recorded yet. The Jira Tracker desktop app records which app you're in (on this
          computer only); your focus picture appears here after a day of use.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat
              label="Deep work"
              value={formatDuration(deep)}
              sub={active ? `${Math.round((deep / active) * 100)}% of active time` : undefined}
            />
            <Stat label="Context switches" value={`${avgSwitches}/day`} sub="app or ticket changes" />
            <Stat label="Longest focus" value={formatDuration(longest)} />
            <Stat label="Past work hours" value={formatDuration(late)} />
          </div>

          <div>
            <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-slate-600 dark:text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--viz-tracked)" }} />
                Focus blocks (25m+)
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--cat-away)" }} />
                Other active time
              </span>
            </div>
            <div className="relative flex h-40 items-end gap-2" onMouseLeave={() => setHover(null)}>
              {days.map((d) => {
                const deepH = (d.deep_seconds / max) * 100;
                const restH = ((d.active_seconds - d.deep_seconds) / max) * 100;
                return (
                  <div
                    key={d.date}
                    className="flex h-full flex-1 flex-col items-center justify-end"
                    onMouseEnter={() => setHover(d)}
                  >
                    <div className="flex w-full max-w-[44px] flex-col justify-end gap-[2px]" style={{ height: "100%" }}>
                      {restH > 0 && (
                        <div className="w-full rounded-t-[4px]" style={{ height: `${restH}%`, background: "var(--cat-away)" }} />
                      )}
                      {deepH > 0 && (
                        <div
                          className={`w-full ${restH > 0 ? "" : "rounded-t-[4px]"}`}
                          style={{ height: `${deepH}%`, background: "var(--viz-tracked)" }}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
              {hover && (
                <div className="pointer-events-none absolute left-1/2 top-0 z-10 -translate-x-1/2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
                  <div className="font-medium">{formatDateKey(hover.date, { weekday: "long", day: "numeric", month: "short" })}</div>
                  <div className="text-slate-500 dark:text-slate-400">
                    {formatDuration(hover.active_seconds)} active · {formatDuration(hover.deep_seconds)} in{" "}
                    {hover.deep_blocks} focus block{hover.deep_blocks === 1 ? "" : "s"}
                  </div>
                  <div className="text-slate-500 dark:text-slate-400">
                    {hover.switches} switches · {formatDuration(hover.tracked_seconds)} tracked
                  </div>
                </div>
              )}
            </div>
            <div className="mt-1 flex gap-2">
              {days.map((d) => (
                <div key={d.date} className="flex-1 text-center text-[11px] text-slate-400">
                  {formatDateKey(d.date, { weekday: "short" })}
                </div>
              ))}
            </div>
          </div>

          {r.tips.length > 0 && (
            <ul className="space-y-1.5">
              {r.tips.map((t) => (
                <li key={t} className="flex gap-2 text-sm text-slate-600 dark:text-slate-300">
                  <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                  {t}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
