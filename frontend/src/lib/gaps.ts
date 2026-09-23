// Gap detection: find stretches of the workday that no session covers, so the
// user can log forgotten time. Pure and timezone-correct by construction: it
// works entirely in the browser's local time (all Date math is local), because
// "the workday" is a human, local-clock notion. The backend stores UTC; the
// sessions we receive carry ISO timestamps that Date parses to local.

export interface BusyInput {
  started_at: string; // ISO
  // Live elapsed for active/paused, effective for completed; already computed
  // by the backend as elapsed_seconds. We treat the session as occupying
  // [start, start + elapsed]. Paused time is thus counted as "busy" here, which
  // is deliberate: you were at your desk on that ticket, just paused the clock.
  elapsed_seconds: number | null;
  state: string;
}

export interface Gap {
  startMs: number;
  endMs: number;
  durationSeconds: number;
}

export interface GapOptions {
  // Work window as local hours, e.g. { startHour: 9, endHour: 18 }.
  startHour: number;
  endHour: number;
  // Ignore gaps shorter than this (lunch-sized noise is opt-in, tiny gaps are
  // just context-switching). Default 15 minutes.
  minGapSeconds?: number;
  // "Now" override for testing. Defaults to Date.now() at call time.
  nowMs?: number;
}

const DAY_MS = 86_400_000;

/** Start-of-today (local midnight) in ms for a given now. */
function startOfLocalDay(nowMs: number): number {
  const d = new Date(nowMs);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/**
 * Compute unaccounted spans within today's work window.
 *
 * The window is [today startHour : today min(endHour, now)]. Sessions are
 * clipped to that window and merged; whatever the merged busy-intervals do not
 * cover, and is at least minGapSeconds long, is returned as a gap. Gaps in the
 * future (after now) are never reported.
 */
export function findGaps(sessions: BusyInput[], opts: GapOptions): Gap[] {
  const nowMs = opts.nowMs ?? Date.now();
  const minGap = (opts.minGapSeconds ?? 15 * 60) * 1000;

  const dayStart = startOfLocalDay(nowMs);
  const windowStart = dayStart + opts.startHour * 3600_000;
  // Never look past the current moment: an unworked future is not a "gap".
  const windowEnd = Math.min(dayStart + opts.endHour * 3600_000, nowMs);
  if (windowEnd <= windowStart) return [];

  // Build busy intervals clipped to the window.
  const intervals: [number, number][] = [];
  for (const s of sessions) {
    const start = Date.parse(s.started_at);
    if (Number.isNaN(start)) continue;
    const secs = Math.max(0, s.elapsed_seconds ?? 0);
    const end = start + secs * 1000;
    const clippedStart = Math.max(start, windowStart);
    const clippedEnd = Math.min(end, windowEnd);
    if (clippedEnd > clippedStart) intervals.push([clippedStart, clippedEnd]);
  }

  // Merge overlapping/adjacent intervals.
  intervals.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const [start, end] of intervals) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }

  // Walk the window, collecting uncovered stretches >= minGap.
  const gaps: Gap[] = [];
  let cursor = windowStart;
  for (const [start, end] of merged) {
    if (start - cursor >= minGap) {
      gaps.push({
        startMs: cursor,
        endMs: start,
        durationSeconds: Math.round((start - cursor) / 1000),
      });
    }
    cursor = Math.max(cursor, end);
  }
  if (windowEnd - cursor >= minGap) {
    gaps.push({
      startMs: cursor,
      endMs: windowEnd,
      durationSeconds: Math.round((windowEnd - cursor) / 1000),
    });
  }
  return gaps;
}

/** Whether an ISO timestamp falls on the local day containing nowMs. */
export function isLocalToday(iso: string, nowMs: number = Date.now()): boolean {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return false;
  const dayStart = startOfLocalDay(nowMs);
  return t >= dayStart && t < dayStart + DAY_MS;
}

/** Format a local ms timestamp as "9:30 AM"-style clock time. */
export function formatClockTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}
