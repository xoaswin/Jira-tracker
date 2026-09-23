// Idle detection (section 11). Tracks the wall-clock gap since the last user
// input. When the tab regains focus after being hidden or idle beyond the
// configured threshold, the caller is told how many minutes were missed so it
// can prompt "keep it, or subtract it?".

import { useEffect, useRef, useState } from "react";

const ACTIVITY_EVENTS = ["mousedown", "keydown", "touchstart", "scroll"] as const;

export function useIdleDetection(thresholdMinutes: number, enabled: boolean) {
  const lastActive = useRef<number>(Date.now());
  const [idleMinutes, setIdleMinutes] = useState<number | null>(null);

  useEffect(() => {
    if (!enabled) return;

    function markActive() {
      lastActive.current = Date.now();
    }

    function checkIdle() {
      const gapMs = Date.now() - lastActive.current;
      const gapMin = Math.floor(gapMs / 60000);
      if (gapMin >= thresholdMinutes) {
        setIdleMinutes(gapMin);
      }
      // Reset the clock so the same gap is not reported repeatedly.
      lastActive.current = Date.now();
    }

    function onVisibility() {
      if (document.visibilityState === "visible") checkIdle();
    }

    for (const ev of ACTIVITY_EVENTS) {
      window.addEventListener(ev, markActive, { passive: true });
    }
    document.addEventListener("visibilitychange", onVisibility);
    // Also poll, so a long idle while the tab stays visible is still caught.
    const interval = window.setInterval(checkIdle, 60000);

    return () => {
      for (const ev of ACTIVITY_EVENTS) {
        window.removeEventListener(ev, markActive);
      }
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(interval);
    };
  }, [thresholdMinutes, enabled]);

  return {
    idleMinutes,
    clearIdle: () => setIdleMinutes(null),
  };
}

// Whether "now" (local time) is at or past the configured HH:MM nudge time.
export function isPastNudgeTime(nudgeTime: string | null | undefined): boolean {
  if (!nudgeTime) return false;
  const [h, m] = nudgeTime.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return false;
  const now = new Date();
  return now.getHours() > h || (now.getHours() === h && now.getMinutes() >= m);
}

/** Minutes-since-local-midnight for an "HH:MM" string, or null if unparseable. */
export function minutesOfDay(hhmm: string | null | undefined): number | null {
  if (!hhmm) return null;
  const [h, m] = hhmm.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

/** Local minutes-since-midnight for a given time (defaults to now). */
export function nowMinutesOfDay(now: Date = new Date()): number {
  return now.getHours() * 60 + now.getMinutes();
}

/**
 * Whether "now" (local) is within [start, end). If end is before start (an
 * overnight shift), the window wraps past midnight. Either bound missing => the
 * window is considered "not configured" and this returns false.
 */
export function isWithinWorkWindow(
  start: string | null | undefined,
  end: string | null | undefined,
  now: Date = new Date(),
): boolean {
  const s = minutesOfDay(start);
  const e = minutesOfDay(end);
  if (s == null || e == null) return false;
  const cur = nowMinutesOfDay(now);
  if (s <= e) return cur >= s && cur < e;
  // Overnight window (e.g. 21:00 -> 06:00).
  return cur >= s || cur < e;
}

/** Whether "now" (local) is at or past the work-end time today. */
export function isPastWorkEnd(
  end: string | null | undefined,
  now: Date = new Date(),
): boolean {
  const e = minutesOfDay(end);
  if (e == null) return false;
  return nowMinutesOfDay(now) >= e;
}
