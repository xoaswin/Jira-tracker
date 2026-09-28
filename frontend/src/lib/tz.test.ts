import { afterEach, describe, expect, it } from "vitest";
import {
  formatDateKey,
  getAppTimeZone,
  setAppTimeZone,
  startOfZonedDay,
  zonedDateStr,
  zonedMinutesOfDay,
  zonedWallToMs,
} from "./tz";

const original = getAppTimeZone();
afterEach(() => setAppTimeZone(original));

describe("app timezone (IST) regardless of machine clock", () => {
  it("maps IST wall time to the right instant", () => {
    setAppTimeZone("Asia/Kolkata");
    expect(new Date(zonedWallToMs("2026-09-28", 12, 0)).toISOString()).toBe(
      "2026-09-28T06:30:00.000Z",
    );
  });

  it("puts a late-UTC-evening instant on the next IST day", () => {
    setAppTimeZone("Asia/Kolkata");
    const t = Date.parse("2026-09-27T20:00:00Z"); // 01:30 IST on the 28th
    expect(zonedDateStr(t)).toBe("2026-09-28");
    expect(zonedMinutesOfDay(t)).toBe(90);
    expect(new Date(startOfZonedDay(t)).toISOString()).toBe("2026-09-27T18:30:00.000Z");
  });

  it("ignores an invalid zone", () => {
    setAppTimeZone("Asia/Kolkata");
    setAppTimeZone("Not/AZone");
    expect(getAppTimeZone()).toBe("Asia/Kolkata");
  });

  it("formats a date key without shifting the day", () => {
    expect(formatDateKey("2026-09-30", { day: "numeric" })).toBe("30");
  });
});
