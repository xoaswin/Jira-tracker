import { describe, expect, it } from "vitest";
import { findGaps, isLocalToday, type BusyInput } from "./gaps";

// Build a local-time timestamp for "today at HH:MM" so tests are independent of
// the machine's timezone (findGaps works in local time throughout).
function todayAt(hour: number, minute = 0): number {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  return d.getTime();
}

function session(startHour: number, startMin: number, durationMin: number): BusyInput {
  return {
    started_at: new Date(todayAt(startHour, startMin)).toISOString(),
    elapsed_seconds: durationMin * 60,
    state: "completed",
  };
}

const NOON_OPTS = {
  startHour: 9,
  endHour: 18,
  minGapSeconds: 15 * 60,
  nowMs: todayAt(18, 0), // evaluate as if the workday is over
};

describe("findGaps", () => {
  it("reports the whole window when there are no sessions", () => {
    const gaps = findGaps([], NOON_OPTS);
    expect(gaps).toHaveLength(1);
    expect(gaps[0].durationSeconds).toBe(9 * 3600);
  });

  it("finds a gap between two sessions", () => {
    // 9:00-10:00 work, then 11:00-12:00 work => 10:00-11:00 gap.
    const gaps = findGaps([session(9, 0, 60), session(11, 0, 60)], {
      ...NOON_OPTS,
    });
    // Gaps: 10-11 (the middle), and 12-18 (trailing). Both >= 15m.
    expect(gaps.length).toBeGreaterThanOrEqual(1);
    const middle = gaps.find((g) => g.durationSeconds === 3600);
    expect(middle).toBeTruthy();
  });

  it("ignores gaps shorter than minGapSeconds", () => {
    // 9:00-9:50 and 10:00-18:00 leaves only a 10-minute gap: below the 15m floor.
    const gaps = findGaps([session(9, 0, 50), session(10, 0, 480)], NOON_OPTS);
    expect(gaps).toHaveLength(0);
  });

  it("merges overlapping sessions before computing gaps", () => {
    // Two overlapping sessions 9-11 and 10-12 cover 9-12 with no internal gap.
    const gaps = findGaps([session(9, 0, 120), session(10, 0, 120)], NOON_OPTS);
    // Only the trailing 12-18 gap remains.
    expect(gaps).toHaveLength(1);
    expect(gaps[0].durationSeconds).toBe(6 * 3600);
  });

  it("never reports gaps in the future (after now)", () => {
    // Now is 11:00; a full 9-11 session means no past gap, and 11-18 is future.
    const gaps = findGaps([session(9, 0, 120)], {
      startHour: 9,
      endHour: 18,
      minGapSeconds: 15 * 60,
      nowMs: todayAt(11, 0),
    });
    expect(gaps).toHaveLength(0);
  });

  it("clips a session that starts before the work window", () => {
    // Session 8:00-9:30 clipped to 9:00; window 9-18, now 18 => gap 9:30-18.
    const gaps = findGaps([session(8, 0, 90)], NOON_OPTS);
    expect(gaps).toHaveLength(1);
    // 9:30 -> 18:00 = 8.5h
    expect(gaps[0].durationSeconds).toBe(Math.round(8.5 * 3600));
  });
});

describe("isLocalToday", () => {
  it("is true for a timestamp earlier today", () => {
    expect(isLocalToday(new Date(todayAt(9, 0)).toISOString(), todayAt(15, 0))).toBe(true);
  });
  it("is false for yesterday", () => {
    const yesterday = todayAt(9, 0) - 86_400_000;
    expect(isLocalToday(new Date(yesterday).toISOString(), todayAt(15, 0))).toBe(false);
  });
});
