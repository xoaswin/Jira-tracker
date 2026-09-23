// Insights: "where my time goes". Analytics over a chosen range built from the
// sessions the app has been accumulating: totals, tracked-vs-logged, and
// breakdowns by project / type / ticket, plus git<->time reconciliation.

import { useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  GitCommitHorizontal,
} from "lucide-react";
import { useInsights, useReconcile } from "../api/hooks";
import type { InsightBucket, ReconcileRow } from "../api/types";
import { useUi } from "../store/ui";
import { formatDuration, toHours } from "../lib/time";
import { Banner, Button, Card, Spinner } from "../components/ui";

const PRESETS: { key: string; label: string }[] = [
  { key: "week", label: "This week" },
  { key: "last_week", label: "Last week" },
  { key: "month", label: "This month" },
  { key: "30d", label: "Last 30 days" },
];

export function Insights() {
  const [preset, setPreset] = useState("week");
  const q = useInsights(preset);
  const data = q.data;

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Insights</h1>
          <p className="mt-1 text-sm text-slate-500">Where your time went.</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPreset(p.key)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium ${
                preset === p.key
                  ? "bg-indigo-600 text-white"
                  : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="error">{String(q.error)}</Banner>}

      {data && data.session_count === 0 && (
        <Card>
          <p className="py-6 text-center text-sm text-slate-400">
            No completed sessions in this range.
          </p>
        </Card>
      )}

      {data && data.session_count > 0 && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <StatTile label="Tracked" value={`${toHours(data.total_tracked_seconds)}h`} />
            <StatTile label="Logged to Jira" value={`${toHours(data.total_logged_seconds)}h`} />
            <StatTile label="Tickets" value={String(data.ticket_count)} />
          </div>

          <BarCard title="By project" buckets={data.by_project} />
          <BarCard title="By type" buckets={data.by_type} />
          <BarCard title="Top tickets" buckets={data.by_ticket} mono />
          <DayTrend buckets={data.by_day} />
        </>
      )}

      <ReconcileCard preset={preset} />
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </Card>
  );
}

function BarCard({
  title,
  buckets,
  mono = false,
}: {
  title: string;
  buckets: InsightBucket[];
  mono?: boolean;
}) {
  if (buckets.length === 0) return null;
  const max = Math.max(...buckets.map((b) => b.tracked_seconds), 1);
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
        <BarChart3 className="h-4 w-4 text-indigo-500" />
        {title}
      </h2>
      <ul className="space-y-2">
        {buckets.map((b) => (
          <li key={b.key} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span
                className={`truncate ${mono ? "font-mono text-indigo-600 dark:text-indigo-400" : "text-slate-600 dark:text-slate-300"}`}
              >
                {b.label}
              </span>
              <span className="shrink-0 text-slate-400">
                {formatDuration(b.tracked_seconds)}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full bg-indigo-500"
                style={{ width: `${Math.round((b.tracked_seconds / max) * 100)}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// A compact per-day column chart for the trend.
function DayTrend({ buckets }: { buckets: InsightBucket[] }) {
  if (buckets.length <= 1) return null;
  const max = Math.max(...buckets.map((b) => b.tracked_seconds), 1);
  return (
    <Card className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300">
        Daily trend
      </h2>
      <div className="flex items-end gap-1" style={{ height: 96 }}>
        {buckets.map((b) => {
          const h = Math.round((b.tracked_seconds / max) * 88);
          const day = new Date(`${b.key}T00:00:00`).toLocaleDateString([], {
            weekday: "short",
          });
          return (
            <div key={b.key} className="flex flex-1 flex-col items-center justify-end gap-1">
              <div
                className="w-full rounded-t bg-indigo-500"
                style={{ height: `${Math.max(2, h)}px` }}
                title={`${b.key}: ${formatDuration(b.tracked_seconds)}`}
              />
              <span className="text-[10px] text-slate-400">{day}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function ReconcileCard({ preset }: { preset: string }) {
  const [open, setOpen] = useState(false);
  const q = useReconcile(preset, open);
  const { openInManage } = useUi();

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <GitCommitHorizontal className="h-4 w-4" />
        Check git vs logged time
      </Button>
    );
  }

  const rows = q.data?.rows ?? [];
  const flagged = rows.filter((r) => r.flag !== "ok");

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <GitCommitHorizontal className="h-4 w-4 text-indigo-500" />
          Git vs logged time
        </h2>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>

      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="error">{String(q.error)}</Banner>}
      {q.data && flagged.length === 0 && (
        <p className="flex items-center gap-2 py-2 text-sm text-emerald-500">
          <CheckCircle2 className="h-4 w-4" /> Everything lines up.
        </p>
      )}
      {q.data && flagged.length === 0 && rows.length === 0 && (
        <p className="text-xs text-slate-400">
          No commits or logged time found. Configure GIT_REPO_PATHS to include
          the git side.
        </p>
      )}

      {flagged.length > 0 && (
        <ul className="space-y-2">
          {flagged.map((r) => (
            <ReconcileRowView key={r.issue_key} row={r} onManage={() => openInManage(r.issue_key)} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function ReconcileRowView({ row, onManage }: { row: ReconcileRow; onManage: () => void }) {
  const isCommitsNoTime = row.flag === "commits_no_time";
  return (
    <li className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
      <div className="min-w-0">
        <span className="font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
          {row.issue_key}
        </span>
        <p
          className={`text-xs ${isCommitsNoTime ? "text-amber-600 dark:text-amber-400" : "text-slate-400"}`}
        >
          {isCommitsNoTime ? (
            <>
              <AlertTriangle className="mr-1 inline h-3 w-3" />
              {row.commit_count} commit{row.commit_count === 1 ? "" : "s"}, no logged time
            </>
          ) : (
            <>
              {formatDuration(row.logged_seconds)} logged, no commits
            </>
          )}
        </p>
      </div>
      <Button variant="ghost" onClick={onManage}>
        {isCommitsNoTime ? "Log it" : "Review"}
      </Button>
    </li>
  );
}
