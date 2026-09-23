// Pure time helpers used by the timer and reports.

interface ElapsedFields {
  started_at: string;
  ended_at: string | null;
  paused_seconds: number;
  paused_at?: string | null;
  adjusted_seconds: number | null;
  state: string;
}

/**
 * Live elapsed seconds for a session, mirroring the backend timer math so the
 * clock can tick client-side between fetches.
 */
export function sessionElapsedSeconds(
  s: ElapsedFields,
  nowMs: number = Date.now(),
): number {
  const started = Date.parse(s.started_at);
  if (s.state === "completed") {
    if (s.adjusted_seconds != null) return Math.max(0, s.adjusted_seconds);
    const ended = s.ended_at ? Date.parse(s.ended_at) : nowMs;
    return Math.max(
      0,
      Math.floor((ended - started) / 1000) - (s.paused_seconds || 0),
    );
  }
  let currentPause = 0;
  if (s.state === "paused" && s.paused_at) {
    currentPause = Math.floor((nowMs - Date.parse(s.paused_at)) / 1000);
  }
  return Math.max(
    0,
    Math.floor((nowMs - started) / 1000) - (s.paused_seconds || 0) - currentPause,
  );
}


/** Format a number of seconds as a compact "1h 23m 45s" style string. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const parts: string[] = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes || hours) parts.push(`${minutes}m`);
  parts.push(`${seconds}s`);
  return parts.join(" ");
}

/** Format seconds as HH:MM:SS for the large running clock. */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

/** Whole hours with one decimal, for the weekly report ("1.5h"). */
export function toHours(totalSeconds: number): number {
  return Math.round((totalSeconds / 3600) * 10) / 10;
}

/** Parse a "1h 30m" / "90m" / "1.5h" free-text duration to seconds, or null. */
export function parseDurationToSeconds(input: string): number | null {
  const text = input.trim().toLowerCase();
  if (!text) return null;

  // Pure number = minutes.
  if (/^\d+(\.\d+)?$/.test(text)) {
    return Math.round(parseFloat(text) * 60);
  }

  const re = /(\d+(?:\.\d+)?)\s*(h|m|s)/g;
  let match: RegExpExecArray | null;
  let seconds = 0;
  let found = false;
  while ((match = re.exec(text)) !== null) {
    found = true;
    const value = parseFloat(match[1]);
    if (match[2] === "h") seconds += value * 3600;
    else if (match[2] === "m") seconds += value * 60;
    else seconds += value;
  }
  return found ? Math.round(seconds) : null;
}
