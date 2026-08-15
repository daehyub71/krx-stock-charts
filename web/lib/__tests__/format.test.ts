import { describe, it, expect } from "vitest";
import { won, pct, volume, changeOf } from "@/lib/format";

describe("won", () => {
  it("groups thousands", () => expect(won(1234567)).toBe("1,234,567"));
  it("rounds fractions", () => expect(won(1234.6)).toBe("1,235"));
  it("handles zero", () => expect(won(0)).toBe("0"));
});

describe("pct", () => {
  it("prefixes a plus sign when positive", () => expect(pct(1.234)).toBe("+1.23%"));
  it("keeps the minus sign", () => expect(pct(-1.235)).toBe("-1.24%"));
  it("marks zero as positive-signed", () => expect(pct(0)).toBe("+0.00%"));
});

describe("volume", () => {
  it("uses 억 above one hundred million", () => expect(volume(250_000_000)).toBe("2.5억"));
  it("uses 만 above ten thousand", () => expect(volume(12_345)).toBe("1.2만"));
  it("drops the decimal for large 만 values", () => expect(volume(1_200_000)).toBe("120만"));
  it("prints small numbers plainly", () => expect(volume(842)).toBe("842"));
});

describe("changeOf", () => {
  it("computes absolute and percent change against the previous close", () => {
    const c = changeOf(110, 100);
    expect(c.abs).toBe(10);
    expect(c.pct).toBeCloseTo(10, 5);
    expect(c.direction).toBe("up");
  });

  it("marks a fall as down", () => {
    expect(changeOf(90, 100).direction).toBe("down");
  });

  it("treats an unchanged close as flat", () => {
    expect(changeOf(100, 100).direction).toBe("flat");
  });

  it("is safe when there is no previous bar", () => {
    const c = changeOf(100, null);
    expect(c.abs).toBe(0);
    expect(c.pct).toBe(0);
    expect(c.direction).toBe("flat");
  });
});
