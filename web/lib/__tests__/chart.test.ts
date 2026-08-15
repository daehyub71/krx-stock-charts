import { describe, it, expect } from "vitest";
import { toCandles, toVolumeBars, toLinePoints, maSeries, formatTickMark } from "@/lib/chart";
import type { Bar } from "@/lib/types";

function bar(d: string, o: number, h: number, l: number, c: number, v = 100): Bar {
  return { d, o, h, l, c, v, a: null };
}

const BARS: Bar[] = [
  bar("2026-08-10", 100, 110, 95, 105),
  bar("2026-08-11", 105, 115, 100, 102), // 하락봉
  bar("2026-08-12", 102, 120, 101, 118),
];

describe("toCandles", () => {
  it("maps OHLC onto the chart's field names", () => {
    expect(toCandles(BARS)[0]).toEqual({
      time: "2026-08-10", open: 100, high: 110, low: 95, close: 105,
    });
  });

  it("keeps the input order", () => {
    expect(toCandles(BARS).map((c) => c.time)).toEqual([
      "2026-08-10", "2026-08-11", "2026-08-12",
    ]);
  });

  it("handles an empty series", () => expect(toCandles([])).toEqual([]));
});

describe("toVolumeBars", () => {
  const palette = { up: "#c8372d", down: "#2e6fbf" };

  it("colours a rising bar with the up colour", () => {
    expect(toVolumeBars([BARS[0]], palette)[0].color).toBe("#c8372d");
  });

  it("colours a falling bar with the down colour", () => {
    expect(toVolumeBars([BARS[1]], palette)[0].color).toBe("#2e6fbf");
  });

  it("treats an unchanged close as rising, matching the candle body", () => {
    const flat = bar("2026-08-10", 100, 110, 95, 100);
    expect(toVolumeBars([flat], palette)[0].color).toBe("#c8372d");
  });

  it("carries the volume through as the value", () => {
    expect(toVolumeBars(BARS, palette).map((b) => b.value)).toEqual([100, 100, 100]);
  });
});

describe("toLinePoints", () => {
  it("drops leading nulls so the line starts where data begins", () => {
    const pts = toLinePoints(BARS, [null, 100, 110]);
    expect(pts).toEqual([
      { time: "2026-08-11", value: 100 },
      { time: "2026-08-12", value: 110 },
    ]);
  });

  it("returns nothing when every value is null", () => {
    expect(toLinePoints(BARS, [null, null, null])).toEqual([]);
  });

  it("ignores values beyond the bar count", () => {
    expect(toLinePoints([BARS[0]], [10, 20, 30])).toHaveLength(1);
  });
});

describe("maSeries", () => {
  const colors = ["#a", "#b", "#c", "#d"];

  it("builds one entry per configured MA period", () => {
    const out = maSeries(BARS, "monthly", 0, colors);
    expect(out.map((s) => s.period)).toEqual([3, 12]);
  });

  it("assigns colours in the fixed palette order", () => {
    const out = maSeries(BARS, "monthly", 0, colors);
    expect(out.map((s) => s.color)).toEqual(["#a", "#b"]);
  });

  it("labels each line with its period", () => {
    expect(maSeries(BARS, "monthly", 0, colors)[0].label).toBe("MA3");
  });

  it("drops the warmup slice from the plotted points", () => {
    // 6봉 중 앞 3봉이 워밍업이면, MA3는 표시 3봉에 대해서만 점을 만든다
    const bars = Array.from({ length: 6 }, (_, i) =>
      bar(`2026-08-1${i}`, 100, 100, 100, 100 + i),
    );
    const out = maSeries(bars, "monthly", 3, colors);
    const ma3 = out.find((s) => s.period === 3)!;
    expect(ma3.points.every((p) => p.time >= "2026-08-13")).toBe(true);
  });

  it("reports the latest value for the legend", () => {
    const bars = Array.from({ length: 5 }, (_, i) =>
      bar(`2026-08-1${i}`, 100, 100, 100, 10 * (i + 1)),
    );
    const ma3 = maSeries(bars, "monthly", 0, colors).find((s) => s.period === 3)!;
    expect(ma3.latest).toBeCloseTo(40, 5); // (30+40+50)/3
  });

  it("has a null latest when the series is too short", () => {
    const ma12 = maSeries(BARS, "monthly", 0, colors).find((s) => s.period === 12)!;
    expect(ma12.latest).toBeNull();
    expect(ma12.points).toEqual([]);
  });
});

describe("formatTickMark", () => {
  it("labels a year tick with the year", () => {
    expect(formatTickMark("2026-01-02", 0)).toBe("2026년");
  });

  it("labels a month tick with the month", () => {
    expect(formatTickMark("2026-08-03", 1)).toBe("8월");
  });

  it("keeps the month on day ticks so the axis reads consistently", () => {
    // 기본 포매터는 여기서 "7일"만 찍어 월 라벨 사이에 섞인다
    expect(formatTickMark("2025-12-07", 2)).toBe("12/7");
  });

  it("accepts a UTC timestamp as well as an ISO string", () => {
    const ts = Date.UTC(2026, 7, 14) / 1000;
    expect(formatTickMark(ts, 1)).toBe("8월");
  });

  it("drops leading zeros from month and day", () => {
    expect(formatTickMark("2026-03-05", 2)).toBe("3/5");
  });
});
