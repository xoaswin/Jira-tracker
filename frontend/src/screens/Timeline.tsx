// Day timeline: app activity, tracked sessions, git commits and untracked gaps
// on one time axis (app timezone). Drag across the chart, or click a gap, to
// select a span and log it to a ticket in one step.

import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight, GitCommit, Plus } from "lucide-react";
import { api } from "../api/client";
import { useManualSession, useMyTickets } from "../api/hooks";
import type { ActivityBlock, ActivityCategory, DayTimeline, TimelineSession } from "../api/types";
import { formatHm as formatDuration } from "../lib/time";
import {
  formatClock,
  formatDateKey,
  zonedDateStr,
  zonedMinutesOfDay,
  zonedWallToMs,
} from "../lib/tz";
import { Banner, Button, Card, Label, Spinner, TextInput } from "../components/ui";

const CATEGORIES: { key: ActivityCategory; label: string }[] = [
  { key: "code", label: "Code" },
  { key: "browser", label: "Browser" },
  { key: "meeting", label: "Meetings" },
  { key: "chat", label: "Chat & mail" },
  { key: "docs", label: "Docs" },
  { key: "other", label: "Other" },
  { key: "away", label: "Away" },
];
const SNAP_MS = 5 * 60_000;
const MIN_GAP_MS = 10 * 60_000;
const ROW_LABEL_W = 72;

const catVar = (c: ActivityCategory) => `var(--cat-${c})`;
// Auto-tracked sessions get a diagonal texture so "auto" never rides on colour alone.
const AUTO_TEXTURE =
  "repeating-linear-gradient(135deg, rgba(255,255,255,0.28) 0 3px, transparent 3px 7px)";

// Start of the app-timezone hour containing t (IST hours start at :00 IST,
// which is :30 UTC, so UTC arithmetic would put ticks on the half hour).
function hourFloor(t: number): number {
  return zonedWallToMs(zonedDateStr(t), Math.floor(zonedMinutesOfDay(t) / 60));
}
function hourCeil(t: number): number {
  const f = hourFloor(t);
  return f === t ? t : f + 3_600_000;
}

function shiftDate(date: string, days: number): string {
  const [y, m, d] = date.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return t.toISOString().slice(0, 10);
}

interface Span {
  a: number;
  b: number;
}

interface Tip {
  x: number;
  y: number;
  lines: string[];
}

function computeGaps(tl: DayTimeline): Span[] {
  const now = Date.parse(tl.now);
  const winA = tl.work ? Date.parse(tl.work.start) : null;
  const winB = tl.work ? Math.min(Date.parse(tl.work.end), now) : null;
  if (winA == null || winB == null || winB <= winA) return [];
  const busy = tl.sessions
    .map((s) => ({ a: Date.parse(s.start), b: Date.parse(s.end) }))
    .sort((x, y) => x.a - y.a);
  const gaps: Span[] = [];
  let cursor = winA;
  for (const s of busy) {
    if (s.b <= cursor) continue;
    if (s.a > cursor && s.a - cursor >= MIN_GAP_MS) gaps.push({ a: cursor, b: Math.min(s.a, winB) });
    cursor = Math.max(cursor, s.b);
    if (cursor >= winB) break;
  }
  if (winB - cursor >= MIN_GAP_MS) gaps.push({ a: cursor, b: winB });
  return gaps.filter((g) => g.b - g.a >= MIN_GAP_MS);
}

export function Timeline() {
  const [date, setDate] = useState(zonedDateStr());
  const today = zonedDateStr();
  const q = useQuery({
    queryKey: ["activity-day", date],
    queryFn: () => api.activityDay(date),
    refetchInterval: date === today ? 60_000 : false,
  });
  const tl = q.data;

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Timeline</h1>
          <p className="mt-1 text-sm text-slate-500">
            What you actually did, next to what you tracked. Drag across the chart, or
            click an amber gap, to log time.
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" onClick={() => setDate(shiftDate(date, -1))} title="Previous day">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="flex items-center gap-1.5 px-2 text-sm font-medium">
            <CalendarDays className="h-4 w-4 text-slate-400" />
            {formatDateKey(date, { weekday: "short", day: "numeric", month: "short" })}
          </span>
          <Button
            variant="ghost"
            onClick={() => setDate(shiftDate(date, 1))}
            disabled={date >= today}
            title="Next day"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          {date !== today && (
            <Button variant="secondary" onClick={() => setDate(today)}>
              Today
            </Button>
          )}
        </div>
      </div>

      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="error">{String(q.error)}</Banner>}
      {tl && !tl.recording && (
        <Banner tone="info">
          No activity recorded yet. Activity is recorded by the Jira Tracker desktop app while
          it runs, and stays on this computer. Sessions and commits still show below.
        </Banner>
      )}
      {tl && <DayChart key={tl.date} tl={tl} />}
    </div>
  );
}

function DayChart({ tl }: { tl: DayTimeline }) {
  const qc = useQueryClient();
  const plotRef = useRef<HTMLDivElement>(null);
  const [sel, setSel] = useState<Span | null>(null);
  const [drag, setDrag] = useState<{ start: number; cur: number } | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);

  const gaps = useMemo(() => computeGaps(tl), [tl]);

  // Axis range: the work window (or the data), widened to cover everything shown.
  const [lo, hi] = useMemo(() => {
    const now = Date.parse(tl.now);
    const dayA = Date.parse(tl.day_start);
    const dayB = Math.min(Date.parse(tl.day_end), Math.max(now, dayA));
    const pts: number[] = [];
    if (tl.work) pts.push(Date.parse(tl.work.start), Date.parse(tl.work.end));
    for (const b of tl.activity) pts.push(Date.parse(b.start), Date.parse(b.end));
    for (const s of tl.sessions) pts.push(Date.parse(s.start), Date.parse(s.end));
    for (const c of tl.commits) pts.push(Date.parse(c.at));
    let a = pts.length ? Math.min(...pts) : zonedWallToMs(tl.date, 9);
    let b = pts.length ? Math.max(...pts) : zonedWallToMs(tl.date, 18);
    a = Math.max(dayA, hourFloor(a));
    b = Math.min(Math.max(dayB, a + 3_600_000), hourCeil(b));
    return [a, Math.max(b, a + 3_600_000)];
  }, [tl]);

  const pct = (t: number) => `${((Math.min(Math.max(t, lo), hi) - lo) / (hi - lo)) * 100}%`;
  const width = (a: number, b: number) =>
    `${((Math.min(b, hi) - Math.max(a, lo)) / (hi - lo)) * 100}%`;

  const hours: number[] = [];
  for (let t = hourCeil(lo); t <= hi; t += 3_600_000) hours.push(t);
  const every = hours.length > 14 ? 2 : 1;

  function timeAt(clientX: number): number {
    const r = plotRef.current!.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    return lo + f * (hi - lo);
  }
  const snap = (t: number) => Math.round(t / SNAP_MS) * SNAP_MS;

  function showTip(e: React.MouseEvent, lines: string[]) {
    const host = plotRef.current!.parentElement!.getBoundingClientRect();
    setTip({ x: e.clientX - host.left, y: e.clientY - host.top, lines });
  }

  const onDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const t = timeAt(e.clientX);
    setDrag({ start: t, cur: t });
  };
  const onMove = (e: React.PointerEvent) => {
    if (drag) setDrag({ ...drag, cur: timeAt(e.clientX) });
  };
  const onUp = () => {
    if (!drag) return;
    const a = snap(Math.min(drag.start, drag.cur));
    const b = snap(Math.max(drag.start, drag.cur));
    setDrag(null);
    if (b - a >= SNAP_MS) setSel({ a, b: Math.min(b, Date.parse(tl.now)) });
  };

  const liveSel = drag
    ? { a: Math.min(drag.start, drag.cur), b: Math.max(drag.start, drag.cur) }
    : sel;

  const tracked = tl.sessions.reduce((n, s) => n + s.seconds, 0);
  const gapSecs = gaps.reduce((n, g) => n + (g.b - g.a) / 1000, 0);

  return (
    <>
      <Card className="space-y-3">
        {/* Legend with totals: identity is never colour-alone. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-slate-600 dark:text-slate-300">
          {CATEGORIES.filter((c) => tl.by_category[c.key]).map((c) => (
            <span key={c.key} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: catVar(c.key) }} />
              {c.label}
              <span className="text-slate-400">{formatDuration(tl.by_category[c.key] ?? 0)}</span>
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--viz-tracked)" }} />
            Tracked <span className="text-slate-400">{formatDuration(tracked)}</span>
          </span>
          {gapSecs > 0 && (
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm border border-amber-400" style={{ background: "var(--viz-gap)" }} />
              Untracked in work hours <span className="text-slate-400">{formatDuration(gapSecs)}</span>
            </span>
          )}
        </div>

        <div className="relative overflow-x-auto">
          <div className="min-w-[640px]">
            {/* hour axis */}
            <div className="flex">
              <div style={{ width: ROW_LABEL_W }} />
              <div className="relative h-5 flex-1">
                {hours.map((t, i) =>
                  i % every === 0 ? (
                    <span
                      key={t}
                      className={`absolute whitespace-nowrap text-[11px] tabular-nums text-slate-400 ${
                        t === lo ? "" : t === hi ? "-translate-x-full" : "-translate-x-1/2"
                      }`}
                      style={{ left: pct(t) }}
                    >
                      {formatClock(t)}
                    </span>
                  ) : null,
                )}
              </div>
            </div>

            <div className="flex">
              <div className="space-y-2 pt-0.5 text-xs font-medium text-slate-500" style={{ width: ROW_LABEL_W }}>
                <div className="flex h-7 items-center">Apps</div>
                <div className="flex h-7 items-center">Tracked</div>
                <div className="flex h-5 items-center">Commits</div>
              </div>

              <div
                ref={plotRef}
                className="relative flex-1 cursor-crosshair touch-none select-none space-y-2 pt-0.5"
                onPointerDown={onDown}
                onPointerMove={onMove}
                onPointerUp={onUp}
                onMouseLeave={() => setTip(null)}
              >
                {/* recessive hour grid (none on the right edge: it would overflow) */}
                {hours.filter((t) => t < hi).map((t) => (
                  <div
                    key={t}
                    className="pointer-events-none absolute bottom-0 top-0 w-px bg-slate-100 dark:bg-slate-800"
                    style={{ left: pct(t) }}
                  />
                ))}

                <ActivityRow blocks={tl.activity} pct={pct} width={width} showTip={showTip} hideTip={() => setTip(null)} />

                <div className="relative h-7">
                  {gaps.map((g) => (
                    <button
                      key={g.a}
                      type="button"
                      className="absolute top-0 h-7 rounded border border-dashed border-amber-400/80 hover:border-amber-500"
                      style={{ left: pct(g.a), width: width(g.a, g.b), background: "var(--viz-gap)" }}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={() => setSel({ a: g.a, b: g.b })}
                      onMouseMove={(e) =>
                        showTip(e, [
                          `Untracked ${formatClock(g.a)} to ${formatClock(g.b)}`,
                          `${formatDuration((g.b - g.a) / 1000)} · click to log`,
                        ])
                      }
                      onMouseLeave={() => setTip(null)}
                      aria-label={`Untracked from ${formatClock(g.a)} to ${formatClock(g.b)}`}
                    />
                  ))}
                  {tl.sessions.map((s) => (
                    <SessionBar key={s.id} s={s} pct={pct} width={width} showTip={showTip} hideTip={() => setTip(null)} />
                  ))}
                </div>

                <div className="relative h-5">
                  {tl.commits.map((c) => (
                    <span
                      key={c.at + c.subject}
                      className="absolute top-0 flex h-5 w-3 -translate-x-1/2 justify-center"
                      style={{ left: pct(Date.parse(c.at)) }}
                      onMouseMove={(e) =>
                        showTip(e, [`${formatClock(c.at)} · ${c.issue_key ?? "commit"}`, c.subject])
                      }
                      onMouseLeave={() => setTip(null)}
                    >
                      <span className="h-5 w-0.5 rounded bg-slate-500 dark:bg-slate-300" />
                    </span>
                  ))}
                </div>

                {/* now line */}
                {Date.parse(tl.now) < hi && (
                  <div
                    className="pointer-events-none absolute bottom-0 top-0 w-0.5 bg-rose-500/70"
                    style={{ left: pct(Date.parse(tl.now)) }}
                  />
                )}

                {liveSel && (
                  <div
                    className="pointer-events-none absolute bottom-0 top-0 rounded border-2 border-violet-500 bg-violet-500/10"
                    style={{ left: pct(liveSel.a), width: width(liveSel.a, liveSel.b) }}
                  />
                )}
              </div>
            </div>
          </div>

          {tip && (
            <div
              className="pointer-events-none absolute z-10 max-w-xs rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900"
              style={{ left: tip.x + 12, top: tip.y + 12 }}
            >
              {tip.lines.map((l, i) => (
                <div key={i} className={i === 0 ? "font-medium" : "text-slate-500 dark:text-slate-400"}>
                  {l}
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {sel && (
        <LogSpan
          key={`${sel.a}-${sel.b}`}
          span={sel}
          tl={tl}
          onDone={() => {
            setSel(null);
            qc.invalidateQueries({ queryKey: ["activity-day", tl.date] });
          }}
          onCancel={() => setSel(null)}
        />
      )}

      <SessionTable sessions={tl.sessions} />
    </>
  );
}

function ActivityRow({
  blocks,
  pct,
  width,
  showTip,
  hideTip,
}: {
  blocks: ActivityBlock[];
  pct: (t: number) => string;
  width: (a: number, b: number) => string;
  showTip: (e: React.MouseEvent, lines: string[]) => void;
  hideTip: () => void;
}) {
  return (
    <div className="relative h-7 rounded bg-slate-50 dark:bg-slate-900/60">
      {blocks.map((b) => {
        const a = Date.parse(b.start);
        const e = Date.parse(b.end);
        const label = CATEGORIES.find((c) => c.key === b.category)?.label ?? b.category;
        return (
          <div
            key={b.start + b.app}
            className="absolute top-0 h-7 rounded-[3px] border-x border-white dark:border-slate-900"
            style={{ left: pct(a), width: width(a, e), background: catVar(b.category) }}
            onMouseMove={(ev) =>
              showTip(ev, [
                `${formatClock(a)} to ${formatClock(e)} · ${formatDuration(b.seconds)}`,
                b.kind === "active" ? `${label}: ${b.app}` : b.kind === "locked" ? "Screen locked" : "Idle",
                ...(b.issue_key ? [`Ticket ${b.issue_key}`] : []),
                ...(b.kind === "active" && b.title ? [b.title] : []),
              ])
            }
            onMouseLeave={hideTip}
          />
        );
      })}
    </div>
  );
}

function SessionBar({
  s,
  pct,
  width,
  showTip,
  hideTip,
}: {
  s: TimelineSession;
  pct: (t: number) => string;
  width: (a: number, b: number) => string;
  showTip: (e: React.MouseEvent, lines: string[]) => void;
  hideTip: () => void;
}) {
  const a = Date.parse(s.start);
  const b = Date.parse(s.end);
  const auto = s.origin === "auto";
  return (
    <div
      className="absolute top-0 flex h-7 items-center overflow-hidden rounded-[3px] border-x border-white px-1.5 text-[11px] font-semibold text-white dark:border-slate-900"
      style={{
        left: pct(a),
        width: width(a, b),
        background: auto ? `${AUTO_TEXTURE}, var(--viz-tracked)` : "var(--viz-tracked)",
      }}
      onMouseMove={(ev) =>
        showTip(ev, [
          `${s.issue_key ?? "No ticket"} · ${formatDuration(s.seconds)}${auto ? " (auto)" : ""}`,
          s.description,
          `${formatClock(a)} to ${s.state === "completed" ? formatClock(b) : "now"} · ${
            s.sync_state === "synced" ? "logged to Jira" : s.state === "completed" ? "not logged" : s.state
          }`,
        ])
      }
      onMouseLeave={hideTip}
    >
      <span className="truncate">{s.issue_key ?? ""}</span>
    </div>
  );
}

// Suggested ticket for a span: the ticket the recorder saw most, else a commit's.
function suggestKey(tl: DayTimeline, span: Span): string {
  const secs = new Map<string, number>();
  for (const b of tl.activity) {
    if (!b.issue_key) continue;
    const a = Math.max(span.a, Date.parse(b.start));
    const e = Math.min(span.b, Date.parse(b.end));
    if (e > a) secs.set(b.issue_key, (secs.get(b.issue_key) ?? 0) + (e - a));
  }
  let best = "";
  let max = 0;
  for (const [k, v] of secs) if (v > max) [best, max] = [k, v];
  if (best) return best;
  const c = tl.commits.find(
    (x) => x.issue_key && Date.parse(x.at) >= span.a && Date.parse(x.at) <= span.b,
  );
  return c?.issue_key ?? "";
}

function topApps(tl: DayTimeline, span: Span): string {
  const secs = new Map<string, number>();
  for (const b of tl.activity) {
    if (b.kind !== "active") continue;
    const a = Math.max(span.a, Date.parse(b.start));
    const e = Math.min(span.b, Date.parse(b.end));
    if (e > a) secs.set(b.app, (secs.get(b.app) ?? 0) + (e - a));
  }
  return [...secs.entries()]
    .sort((x, y) => y[1] - x[1])
    .slice(0, 3)
    .map(([app, ms]) => `${app} ${formatDuration(ms / 1000)}`)
    .join(" · ");
}

function LogSpan({
  span,
  tl,
  onDone,
  onCancel,
}: {
  span: Span;
  tl: DayTimeline;
  onDone: () => void;
  onCancel: () => void;
}) {
  const manual = useManualSession();
  const tickets = useMyTickets();
  const [key, setKey] = useState(() => suggestKey(tl, span));
  const [desc, setDesc] = useState("");
  const secs = Math.round((span.b - span.a) / 1000);
  const overlaps = tl.sessions.some(
    (s) => Date.parse(s.start) < span.b && Date.parse(s.end) > span.a,
  );
  const apps = topApps(tl, span);
  const ticketSummary = tickets.data?.tickets.find((t) => t.issue_key === key.toUpperCase())?.summary;

  function submit() {
    manual.mutate(
      {
        description: desc.trim() || ticketSummary || key.toUpperCase() || "Work",
        duration_seconds: secs,
        issue_key: key.trim().toUpperCase() || null,
        notes: null,
        started_at: new Date(span.a).toISOString(),
      },
      { onSuccess: onDone },
    );
  }

  return (
    <Card className="space-y-3 border-violet-300 dark:border-violet-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Log {formatClock(span.a)} to {formatClock(span.b)}{" "}
          <span className="font-normal text-slate-500">· {formatDuration(secs)}</span>
        </h2>
        {apps && <span className="text-xs text-slate-400">{apps}</span>}
      </div>
      {overlaps && (
        <Banner tone="warning">This overlaps time you already tracked; it would be logged twice.</Banner>
      )}
      <div className="grid gap-3 sm:grid-cols-[200px_1fr]">
        <div>
          <Label>Ticket</Label>
          <TextInput
            list="timeline-tickets"
            placeholder="PPVM-123"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <datalist id="timeline-tickets">
            {tickets.data?.tickets.map((t) => (
              <option key={t.issue_key} value={t.issue_key}>
                {t.summary}
              </option>
            ))}
          </datalist>
        </div>
        <div>
          <Label>What you did</Label>
          <TextInput
            placeholder={ticketSummary ?? "e.g. code review, debugging the webhook"}
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button onClick={submit} loading={manual.isPending} disabled={!key.trim() && !desc.trim()}>
          <Plus className="h-4 w-4" />
          {key.trim() ? `Log ${formatDuration(secs)} to ${key.trim().toUpperCase()}` : "Save locally"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      {manual.isError && <Banner tone="error">{String(manual.error)}</Banner>}
      {manual.data?.warning && <Banner tone="warning">{manual.data.warning}</Banner>}
    </Card>
  );
}

// Table view of the day's sessions (the chart's accessible equivalent).
function SessionTable({ sessions }: { sessions: TimelineSession[] }) {
  if (!sessions.length) return null;
  return (
    <Card>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
        <GitCommit className="h-4 w-4" />
        Sessions
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400">
              <th className="py-1 pr-3 font-medium">Time</th>
              <th className="py-1 pr-3 font-medium">Ticket</th>
              <th className="py-1 pr-3 font-medium">What</th>
              <th className="py-1 pr-3 text-right font-medium">Duration</th>
              <th className="py-1 font-medium">Jira</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="whitespace-nowrap py-1.5 pr-3 tabular-nums text-slate-500">
                  {formatClock(s.start)}
                </td>
                <td className="py-1.5 pr-3 font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                  {s.issue_key ?? "-"}
                  {s.origin === "auto" && <span className="ml-1 font-sans font-normal text-slate-400">auto</span>}
                </td>
                <td className="max-w-[280px] truncate py-1.5 pr-3">{s.description}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{formatDuration(s.seconds)}</td>
                <td className="py-1.5 text-xs text-slate-500">
                  {s.sync_state === "synced" ? "Logged" : s.state === "completed" ? "Not logged" : "Running"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
