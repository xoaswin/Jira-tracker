// The user's working timezone (settings.timezone). Every "today", work-window
// check and displayed clock time goes through here instead of the browser's own
// zone, so the app shows IST even on a machine whose clock is set elsewhere.
//
// Starts as the browser zone (so tests and the pre-settings first paint behave
// as before) and is switched to the saved setting by App on load.

let appTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
const partsFmt = new Map<string, Intl.DateTimeFormat>();

export const COMMON_TIMEZONES = [
  "Asia/Kolkata",
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Dubai",
  "Asia/Singapore",
  "Australia/Sydney",
];

export function isValidTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

export function setAppTimeZone(tz: string | null | undefined): void {
  if (tz && isValidTimeZone(tz)) appTz = tz;
}

export function getAppTimeZone(): string {
  return appTz;
}

interface Parts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

function zonedParts(ms: number, tz = appTz): Parts {
  let fmt = partsFmt.get(tz);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    partsFmt.set(tz, fmt);
  }
  const out: Record<string, number> = {};
  for (const p of fmt.formatToParts(new Date(ms))) {
    if (p.type !== "literal") out[p.type] = Number(p.value);
  }
  return out as unknown as Parts;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** YYYY-MM-DD of an instant in the app timezone (defaults to now). */
export function zonedDateStr(ms: number = Date.now()): string {
  const p = zonedParts(ms);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

/** Minutes since midnight of an instant in the app timezone. */
export function zonedMinutesOfDay(ms: number = Date.now()): number {
  const p = zonedParts(ms);
  return p.hour * 60 + p.minute;
}

/** The instant a wall-clock time on a YYYY-MM-DD date occurs in the app zone. */
export function zonedWallToMs(dateStr: string, hour = 0, minute = 0, second = 0, msec = 0): number {
  const [y, mo, d] = dateStr.split("-").map(Number);
  const guess = Date.UTC(y, mo - 1, d, hour, minute, second, msec);
  const offsetAt = (t: number) => {
    const p = zonedParts(t);
    return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(t / 1000) * 1000;
  };
  const first = guess - offsetAt(guess);
  // Re-check once in case the offset differs across a DST edge.
  return guess - offsetAt(first);
}

/** Start (00:00) of the app-timezone day containing ``ms``. */
export function startOfZonedDay(ms: number = Date.now()): number {
  return zonedWallToMs(zonedDateStr(ms));
}

/** "9:30 AM"-style clock time in the app timezone. */
export function formatClock(value: number | string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    timeZone: appTz,
  });
}

/** Locale date of an instant in the app timezone. */
export function formatDate(value: number | string, opts: Intl.DateTimeFormatOptions = {}): string {
  return new Date(value).toLocaleDateString([], { ...opts, timeZone: appTz });
}

/** Locale date of a calendar date key ("YYYY-MM-DD"), no zone shifting. */
export function formatDateKey(key: string, opts: Intl.DateTimeFormatOptions = {}): string {
  const [y, m, d] = key.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString([], { ...opts, timeZone: "UTC" });
}
