// Plan My Day: rank the tickets assigned to me and fit them into a capacity
// budget, estimating each from my learned velocity (how long tickets of that
// type actually take me). Shows what fits before the day runs out and what
// spills over, so I can plan realistically instead of guessing.

import { CalendarRange, Gauge, Play } from "lucide-react";
import { useActiveSession, useCreateSession, usePlanToday, useUpdateSession } from "../api/hooks";
import { ApiError } from "../api/client";
import { useUi } from "../store/ui";
import type { PlanItem } from "../api/types";
import { formatDuration, toHours } from "../lib/time";
import { Banner, Button, Card, Spinner } from "./ui";

export function PlanMyDay() {
  const { planCapacityHours, setPlanCapacityHours } = useUi();
  const plan = usePlanToday(planCapacityHours);
  const active = useActiveSession();
  const createSession = useCreateSession();
  const updateSession = useUpdateSession();
  const { setScreen, setCurrentSession } = useUi();

  const hasActive = !!active.data;
  const starting = createSession.isPending || updateSession.isPending;

  function startOnTicket(item: PlanItem) {
    if (hasActive || starting) return;
    const t = item.ticket;
    createSession.mutate(
      { description: `Work on ${t.issue_key}: ${t.summary}`.trim(), board_id: null },
      {
        onSuccess: (session) => {
          updateSession.mutate(
            { id: session.id, patch: { issue_key: t.issue_key, issue_origin: "manual" } },
            {
              onSuccess: () => {
                setCurrentSession(session.id);
                setScreen("active");
              },
            },
          );
        },
      },
    );
  }

  const data = plan.data;

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <CalendarRange className="h-4 w-4 text-indigo-500" />
          Plan my day
        </h2>
        <label className="flex items-center gap-2 text-xs text-slate-500">
          <Gauge className="h-3.5 w-3.5" />
          Capacity
          <input
            type="number"
            min={0}
            max={24}
            step={0.5}
            value={planCapacityHours}
            onChange={(e) =>
              setPlanCapacityHours(Math.max(0, Math.min(24, Number(e.target.value) || 0)))
            }
            className="w-16 rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          h
        </label>
      </div>

      {plan.isLoading && <Spinner />}
      {plan.isError && (
        <Banner tone="error">
          {plan.error instanceof ApiError
            ? JSON.stringify(plan.error.detail)
            : String(plan.error)}
        </Banner>
      )}

      {data && data.items.length === 0 && (
        <p className="py-2 text-sm text-slate-400">
          Nothing assigned to plan. Enjoy the clear runway.
        </p>
      )}

      {data && data.items.length > 0 && (
        <>
          <p className="text-xs text-slate-400">
            {data.total_samples > 0 ? (
              <>
                Estimates learned from {data.total_samples} past session
                {data.total_samples === 1 ? "" : "s"}.
              </>
            ) : (
              <>No history yet, so estimates default to 1h each. They sharpen as you track work.</>
            )}{" "}
            Planned {toHours(data.planned_seconds)}h of {toHours(data.capacity_seconds)}h;{" "}
            {data.overflow_seconds > 0
              ? `${toHours(data.overflow_seconds)}h won't fit today.`
              : "everything fits."}
          </p>

          <ol className="space-y-2">
            {data.items.map((item, i) => (
              <PlanRow
                key={item.ticket.issue_key}
                item={item}
                index={i}
                onStart={() => startOnTicket(item)}
                startDisabled={hasActive || starting}
              />
            ))}
          </ol>
        </>
      )}
    </Card>
  );
}

function PlanRow({
  item,
  index,
  onStart,
  startDisabled,
}: {
  item: PlanItem;
  index: number;
  onStart: () => void;
  startDisabled: boolean;
}) {
  const t = item.ticket;
  return (
    <li
      className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 ${
        item.fits
          ? "border-slate-200 dark:border-slate-800"
          : "border-dashed border-slate-300 opacity-70 dark:border-slate-700"
      }`}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="w-5 shrink-0 text-center text-xs font-semibold text-slate-400">
          {index + 1}
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
              {t.issue_key}
            </span>
            {t.urgency === "overdue" && (
              <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-700 dark:bg-rose-950 dark:text-rose-300">
                overdue
              </span>
            )}
            {t.priority && (
              <span className="text-[10px] text-slate-400">{t.priority}</span>
            )}
          </div>
          <p className="truncate text-sm text-slate-800 dark:text-slate-200">
            {t.summary}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="whitespace-nowrap text-xs text-slate-400">
          ~{formatDuration(item.estimate_seconds)}
          {!item.fits && " · overflow"}
        </span>
        <Button
          variant="ghost"
          onClick={onStart}
          disabled={startDisabled}
          title={startDisabled ? "Finish the active session first" : "Start a timer"}
        >
          <Play className="h-4 w-4" />
          Start
        </Button>
      </div>
    </li>
  );
}
