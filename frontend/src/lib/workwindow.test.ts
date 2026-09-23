import { describe, expect, it } from "vitest";
import {
  isPastWorkEnd,
  isWithinWorkWindow,
  minutesOfDay,
  nowMinutesOfDay,
} from "./idle";

function at(hour: number, minute = 0): Date {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  return d;
}

describe("minutesOfDay", () => {
  it("parses HH:MM", () => {
    expect(minutesOfDay("12:00")).toBe(720);
    expect(minutesOfDay("21:30")).toBe(21 * 60 + 30);
  });
  it("returns null for junk or missing", () => {
    expect(minutesOfDay(null)).toBeNull();
    expect(minutesOfDay("nope")).toBeNull();
  });
});

describe("isWithinWorkWindow", () => {
  it("is true inside a normal daytime window", () => {
    // 12:00-21:00, now 15:00
    expect(isWithinWorkWindow("12:00", "21:00", at(15))).toBe(true);
  });
  it("is false before start and at/after end", () => {
    expect(isWithinWorkWindow("12:00", "21:00", at(11, 59))).toBe(false);
    expect(isWithinWorkWindow("12:00", "21:00", at(21, 0))).toBe(false);
  });
  it("handles an overnight window", () => {
    // 21:00-06:00 wraps midnight.
    expect(isWithinWorkWindow("21:00", "06:00", at(23))).toBe(true);
    expect(isWithinWorkWindow("21:00", "06:00", at(3))).toBe(true);
    expect(isWithinWorkWindow("21:00", "06:00", at(12))).toBe(false);
  });
  it("is false when unconfigured", () => {
    expect(isWithinWorkWindow(null, "21:00", at(15))).toBe(false);
    expect(isWithinWorkWindow("12:00", null, at(15))).toBe(false);
  });
});

describe("isPastWorkEnd", () => {
  it("is true at or after work end", () => {
    expect(isPastWorkEnd("21:00", at(21, 0))).toBe(true);
    expect(isPastWorkEnd("21:00", at(22, 30))).toBe(true);
  });
  it("is false before work end", () => {
    expect(isPastWorkEnd("21:00", at(20, 59))).toBe(false);
  });
  it("is false when unconfigured", () => {
    expect(isPastWorkEnd(null, at(23))).toBe(false);
  });
});

describe("nowMinutesOfDay", () => {
  it("computes minutes since local midnight", () => {
    expect(nowMinutesOfDay(at(1, 30))).toBe(90);
  });
});
