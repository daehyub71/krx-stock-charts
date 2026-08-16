import { describe, it, expect } from "vitest";
import { sma, periodStats, warmupCount } from "@/lib/indicators";
import type { Bar } from "@/lib/types";

function bar(d: string, c: number, h = c, l = c, o = c, v = 100): Bar {
  return { d, o, h, l, c, v, a: null };
}

describe("sma", () => {
  it("returns null until the window is filled", () => {
    const bars = [bar("2026-08-10", 10), bar("2026-08-11", 20), bar("2026-08-12", 30)];
    expect(sma(bars, 3)).toEqual([null, null, 20]);
  });

  it("computes a moving average across the series", () => {
    const bars = [1, 2, 3, 4, 5].map((n, i) => bar(`2026-08-1${i}`, n));
    expect(sma(bars, 2)).toEqual([null, 1.5, 2.5, 3.5, 4.5]);
  });

  it("first valid index equals period minus one", () => {
    const bars = Array.from({ length: 30 }, (_, i) => bar(`d${i}`, i + 1));
    const out = sma(bars, 20);
    expect(out.findIndex((v) => v !== null)).toBe(19);
  });

  it("returns all null when the series is shorter than the period", () => {
    const bars = [bar("2026-08-10", 10), bar("2026-08-11", 20)];
    expect(sma(bars, 5)).toEqual([null, null]);
  });

  it("handles an empty series", () => {
    expect(sma([], 5)).toEqual([]);
  });
});

describe("warmupCount", () => {
  it("is the longest MA period for the timeframe", () => {
    expect(warmupCount("daily")).toBe(120);
    expect(warmupCount("weekly")).toBe(60);
    expect(warmupCount("monthly")).toBe(12);
  });

  it("guarantees MA lines start at the first visible bar", () => {
    // 표시 10봉 + 워밍업 12봉을 읽으면, 뒤 10봉의 MA12가 전부 채워져야 한다
    const total = 10 + warmupCount("monthly");
    const bars = Array.from({ length: total }, (_, i) => bar(`d${i}`, i + 1));
    const visible = sma(bars, 12).slice(warmupCount("monthly"));
    expect(visible).toHaveLength(10);
    expect(visible.every((v) => v !== null)).toBe(true);
  });
});

describe("periodStats", () => {
  const bars = [
    bar("2026-08-10", 100, 110, 90, 100, 1000),
    bar("2026-08-11", 120, 130, 95, 120, 2000),
    bar("2026-08-12", 110, 115, 80, 110, 3000),
  ];

  it("computes return from first open to last close", () => {
    expect(periodStats(bars, "daily").returnPct).toBeCloseTo(10, 5);
  });

  it("finds the period high and low across all bars", () => {
    const s = periodStats(bars, "daily");
    expect(s.high).toBe(130);
    expect(s.low).toBe(80);
  });

  it("averages volume", () => {
    expect(periodStats(bars, "daily").avgVolume).toBe(2000);
  });

  it("annualizes volatility by timeframe", () => {
    const daily = periodStats(bars, "daily").volatility;
    const monthly = periodStats(bars, "monthly").volatility;
    // 같은 수익률 계열이라도 연율화 계수가 달라 일봉 쪽이 크다
    expect(daily).toBeGreaterThan(monthly);
  });

  it("returns zeros for an empty series instead of NaN", () => {
    const s = periodStats([], "daily");
    expect(s.returnPct).toBe(0);
    expect(s.high).toBe(0);
    expect(s.volatility).toBe(0);
  });

  it("handles a single bar without dividing by zero", () => {
    const s = periodStats([bar("2026-08-10", 100)], "daily");
    expect(Number.isFinite(s.volatility)).toBe(true);
    expect(s.returnPct).toBe(0);
  });
});

describe("periodStats — 거래대금", () => {
  function withAmount(d: string, c: number, a: number | null): Bar {
    return { d, o: c, h: c, l: c, c, v: 100, a };
  }

  it("averages amount when every bar has one", () => {
    const bars = [withAmount("d1", 100, 1000), withAmount("d2", 100, 3000)];
    expect(periodStats(bars, "daily").avgAmount).toBe(2000);
  });

  it("returns null when any bar is missing an amount", () => {
    // 일부만 더한 평균은 사실이 아니다 — 백필분과 갱신분이 섞이면 이 경우가 된다
    const bars = [withAmount("d1", 100, 1000), withAmount("d2", 100, null)];
    expect(periodStats(bars, "daily").avgAmount).toBeNull();
  });

  it("returns null for an empty series", () => {
    expect(periodStats([], "daily").avgAmount).toBeNull();
  });
});
