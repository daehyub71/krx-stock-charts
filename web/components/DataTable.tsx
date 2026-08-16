"use client";

/**
 * 시세 표 (DESIGN §3 접근성).
 *
 * 차트와 같은 데이터를 표로도 제공한다 — 색만으로 정보를 전달하지 않기 위한 대체 표현이다.
 */

import { amount, pct, won } from "@/lib/format";
import { TIMEFRAME_LABEL, type Bar, type Timeframe } from "@/lib/types";

export interface DataTableProps {
  bars: readonly Bar[];
  timeframe: Timeframe;
  limit?: number;
}

export default function DataTable({ bars, timeframe, limit = 40 }: DataTableProps) {
  const rows = bars.slice(-limit).reverse();

  return (
    <section className="overflow-hidden rounded-xl border border-[var(--rule)] bg-[var(--surface)]">
      <div className="flex items-center gap-3 px-5 py-3.5">
        <h2 className="text-[13.5px] font-semibold">시세 표</h2>
        <span className="text-[10px] font-semibold uppercase tracking-[0.11em] text-[var(--ink-3)]">
          {TIMEFRAME_LABEL[timeframe]} · 최근 {rows.length}개
        </span>
      </div>
      <div className="overflow-x-auto border-t border-[var(--rule-2)]">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr>
              {["일자", "시가", "고가", "저가", "종가", "등락률", "거래량", "거래대금"].map((h, i) => (
                <th
                  key={h}
                  scope="col"
                  className={`whitespace-nowrap border-b border-[var(--rule)] bg-[var(--inset)] px-5 py-2 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-[var(--ink-3)] ${
                    i === 0 ? "text-left" : "text-right"
                  }`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((b, i) => {
              const prev = rows[i + 1];
              const change = prev ? (b.c / prev.c - 1) * 100 : null;
              return (
                <tr key={b.d} className="hover:bg-[var(--inset)]">
                  <td className="whitespace-nowrap border-b border-[var(--rule-2)] px-5 py-1.5 text-[var(--ink-2)]">
                    {b.d}
                  </td>
                  <Cell>{won(b.o)}</Cell>
                  <Cell>{won(b.h)}</Cell>
                  <Cell>{won(b.l)}</Cell>
                  <Cell bold>{won(b.c)}</Cell>
                  <Cell color={change === null ? undefined : change >= 0 ? "var(--up)" : "var(--down)"}>
                    {change === null ? "—" : pct(change)}
                  </Cell>
                  <Cell>{b.v.toLocaleString("ko-KR")}</Cell>
                  <Cell>{amount(b.a)}</Cell>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Cell({
  children,
  bold,
  color,
}: {
  children: React.ReactNode;
  bold?: boolean;
  color?: string;
}) {
  return (
    <td
      className={`num whitespace-nowrap border-b border-[var(--rule-2)] px-5 py-1.5 text-right ${
        bold ? "font-semibold" : ""
      }`}
      style={color ? { color } : undefined}
    >
      {children}
    </td>
  );
}
