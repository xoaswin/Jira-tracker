import { describe, expect, it } from "vitest";
import {
  formatClock,
  formatDuration,
  parseDurationToSeconds,
  sessionElapsedSeconds,
  toHours,
} from "./time";

describe("formatDuration", () => {
  it("shows seconds only under a minute", () => {
    expect(formatDuration(45)).toBe("45s");
  });
  it("shows minutes and seconds", () => {
    expect(formatDuration(125)).toBe("2m 5s");
  });
  it("shows hours, minutes, seconds", () => {
    expect(formatDuration(3661)).toBe("1h 1m 1s");
  });
  it("clamps negatives to 0s", () => {
    expect(formatDuration(-10)).toBe("0s");
  });
});

describe("formatClock", () => {
  it("zero pads HH:MM:SS", () => {
    expect(formatClock(0)).toBe("00:00:00");
    expect(formatClock(3661)).toBe("01:01:01");
  });
});

describe("toHours", () => {
  it("rounds to one decimal", () => {
    expect(toHours(5400)).toBe(1.5);
    expect(toHours(3600)).toBe(1);
  });
});

describe("parseDurationToSeconds", () => {
  it("treats a bare number as minutes", () => {
    expect(parseDurationToSeconds("90")).toBe(5400);
  });
  it("parses h/m/s units", () => {
    expect(parseDurationToSeconds("1h 30m")).toBe(5400);
    expect(parseDurationToSeconds("1h30m")).toBe(5400);
    expect(parseDurationToSeconds("45s")).toBe(45);
    expect(parseDurationToSeconds("1.5h")).toBe(5400);
  });
  it("returns null for junk", () => {
    expect(parseDurationToSeconds("abc")).toBeNull();
    expect(parseDurationToSeconds("")).toBeNull();
  });
});

describe("sessionElapsedSeconds", () => {
  const start = "2026-09-07T09:00:00.000+00:00";
  const now = Date.parse("2026-09-07T10:00:00.000+00:00"); // +1h

  it("active session counts live minus accumulated pause", () => {
    const s = {
      started_at: start,
      ended_at: null,
      paused_seconds: 600,
      adjusted_seconds: null,
      state: "active",
    };
    expect(sessionElapsedSeconds(s, now)).toBe(3600 - 600);
  });

  it("completed session uses ended minus pause", () => {
    const s = {
      started_at: start,
      ended_at: "2026-09-07T09:30:00.000+00:00",
      paused_seconds: 0,
      adjusted_seconds: null,
      state: "completed",
    };
    expect(sessionElapsedSeconds(s, now)).toBe(1800);
  });

  it("completed session honours manual adjustment", () => {
    const s = {
      started_at: start,
      ended_at: "2026-09-07T09:30:00.000+00:00",
      paused_seconds: 0,
      adjusted_seconds: 1200,
      state: "completed",
    };
    expect(sessionElapsedSeconds(s, now)).toBe(1200);
  });

  it("paused session subtracts the current pause span", () => {
    const s = {
      started_at: start,
      ended_at: null,
      paused_seconds: 0,
      paused_at: "2026-09-07T09:50:00.000+00:00", // paused 10m ago
      adjusted_seconds: null,
      state: "paused",
    };
    expect(sessionElapsedSeconds(s, now)).toBe(3600 - 600);
  });
});
