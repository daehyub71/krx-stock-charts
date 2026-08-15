import { describe, it, expect } from "vitest";
import { PAGE_SIZE, fetchAllPages } from "@/lib/paginate";

/** range(from,to)를 흉내 내는 가짜 쿼리 빌더. */
function fakeQuery(total: number) {
  const calls: Array<[number, number]> = [];
  const build = () => ({
    range(from: number, to: number) {
      calls.push([from, to]);
      const size = to - from + 1;
      // Supabase는 요청 크기와 무관하게 1000행에서 잘라 돌려준다
      const capped = Math.min(size, PAGE_SIZE);
      const rows = Array.from(
        { length: Math.max(0, Math.min(capped, total - from)) },
        (_, i) => ({ id: from + i }),
      );
      return Promise.resolve({ data: rows, error: null });
    },
  });
  return { build, calls };
}

describe("fetchAllPages", () => {
  it("returns everything below one page in a single request", async () => {
    const q = fakeQuery(300);
    const rows = await fetchAllPages(q.build);
    expect(rows).toHaveLength(300);
    expect(q.calls).toHaveLength(1);
  });

  it("pages past the 1000-row cap that Supabase applies silently", async () => {
    const q = fakeQuery(2500);
    const rows = await fetchAllPages(q.build);
    expect(rows).toHaveLength(2500);
    expect(q.calls.length).toBeGreaterThan(1);
  });

  it("stops exactly at the boundary without an extra empty request", async () => {
    const q = fakeQuery(PAGE_SIZE);
    const rows = await fetchAllPages(q.build);
    expect(rows).toHaveLength(PAGE_SIZE);
    // 정확히 한 페이지가 찼으므로 다음 페이지를 한 번 더 확인한다
    expect(q.calls).toHaveLength(2);
  });

  it("returns an empty array when there is nothing", async () => {
    const q = fakeQuery(0);
    expect(await fetchAllPages(q.build)).toEqual([]);
  });

  it("requests contiguous, non-overlapping ranges", async () => {
    const q = fakeQuery(2500);
    await fetchAllPages(q.build);
    for (let i = 1; i < q.calls.length; i++) {
      expect(q.calls[i][0]).toBe(q.calls[i - 1][1] + 1);
    }
  });

  it("throws when the query reports an error", async () => {
    const failing = () => ({
      range: () => Promise.resolve({ data: null, error: { message: "boom" } }),
    });
    await expect(fetchAllPages(failing)).rejects.toThrow(/boom/);
  });

  it("honours a row limit so callers can cap large reads", async () => {
    const q = fakeQuery(5000);
    const rows = await fetchAllPages(q.build, 1200);
    expect(rows).toHaveLength(1200);
  });
});
