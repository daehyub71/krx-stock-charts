import { describe, it, expect } from "vitest";
import { chunk, SPARKLINE_TICKER_CHUNK } from "@/lib/load";

describe("chunk", () => {
  it("splits a list into fixed-size groups", () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
  });

  it("returns a single group when the list fits", () => {
    expect(chunk([1, 2], 10)).toEqual([[1, 2]]);
  });

  it("returns nothing for an empty list", () => {
    expect(chunk([], 10)).toEqual([]);
  });

  it("keeps the whole market inside URL-safe groups", () => {
    // 2,763종목을 한 번에 .in()으로 보내면 URL이 약 19KB가 되어 400이 난다.
    const all = Array.from({ length: 2763 }, (_, i) => `${i}`.padStart(6, "0"));
    const groups = chunk(all, SPARKLINE_TICKER_CHUNK);
    expect(groups.length).toBeGreaterThan(1);
    expect(Math.max(...groups.map((g) => g.length))).toBeLessThanOrEqual(SPARKLINE_TICKER_CHUNK);
    expect(groups.flat()).toHaveLength(2763);
  });

  it("chunk size stays small enough for a query string", () => {
    // 티커 6자 + 구분자 1자 ≈ 7바이트. 브라우저·프록시가 안전하게 다루는 선을 넘지 않는다.
    expect(SPARKLINE_TICKER_CHUNK * 7).toBeLessThan(4000);
  });
});
