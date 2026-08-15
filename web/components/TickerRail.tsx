"use client";

/**
 * 좌측 종목 레일 (DESIGN §1 IA · §5-C 확정 레이아웃).
 *
 * 종목을 갈아타며 비교하는 것이 주 사용 패턴이라 목록을 항상 띄워 둔다.
 * 스파크라인은 최근 26주 종가를 그린다.
 */

import { useMemo, useState } from "react";
import { pct } from "@/lib/format";
import type { Ticker } from "@/lib/types";

export interface TickerRailProps {
  tickers: readonly Ticker[];
  /** {티커: 최근 종가 배열(시간 오름차순)}. */
  sparklines?: Map<string, number[]>;
  selected: string;
  onSelect: (ticker: string) => void;
}

/**
 * 검색어로 종목을 거른다. 종목명과 티커 양쪽을 본다.
 *
 * 대소문자를 구분하지 않는다 — 티커에 대문자가 섞이므로(0126Z0) 소문자로 쳐도 찾혀야 한다.
 */
export function filterTickers(tickers: readonly Ticker[], query: string): Ticker[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...tickers];
  return tickers.filter(
    (t) => t.name.toLowerCase().includes(q) || t.ticker.toLowerCase().includes(q),
  );
}

/** 종가 배열을 스파크라인 path로 만든다. */
export function sparkPath(closes: readonly number[], width: number, height: number): string {
  if (closes.length < 2) return "";
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  return closes
    .map((c, i) => {
      const x = (i / (closes.length - 1)) * width;
      const y = height - ((c - min) / span) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

export default function TickerRail({
  tickers,
  sparklines,
  selected,
  onSelect,
}: TickerRailProps) {
  const [query, setQuery] = useState("");
  const visible = useMemo(() => filterTickers(tickers, query), [tickers, query]);

  return (
    <aside className="overflow-hidden rounded-xl border border-[var(--rule)] bg-[var(--surface)]">
      <div className="border-b border-[var(--rule-2)] p-3.5">
        <div className="text-[10px] font-semibold uppercase tracking-[0.11em] text-[var(--ink-3)]">
          종목
        </div>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="종목명 또는 티커 검색"
          aria-label="종목 검색"
          className="mt-2 w-full rounded-lg border border-[var(--rule)] bg-[var(--inset)] px-3 py-2 text-[13px] text-[var(--ink)] outline-none placeholder:text-[var(--ink-3)] focus:border-[var(--accent)] focus:bg-[var(--surface)]"
        />
      </div>

      <ul role="listbox" aria-label="종목 목록" className="max-h-[560px] overflow-y-auto">
        {visible.map((t) => {
          const closes = sparklines?.get(t.ticker) ?? [];
          const change =
            closes.length >= 2
              ? (closes[closes.length - 1] / closes[closes.length - 2] - 1) * 100
              : 0;
          const color = change >= 0 ? "var(--up)" : "var(--down)";
          const isSelected = t.ticker === selected;

          return (
            <li key={t.ticker}>
              <button
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => onSelect(t.ticker)}
                style={isSelected ? { background: "var(--accent-weak)" } : undefined}
                className={`grid w-full grid-cols-[minmax(0,1fr)_58px_52px] items-center gap-2 border-b border-l-2 border-[var(--rule-2)] px-3.5 py-2 text-left hover:bg-[var(--inset)] ${
                  isSelected ? "border-l-[var(--accent)]" : "border-l-transparent"
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium">{t.name}</span>
                  <span className="num block text-[10.5px] text-[var(--ink-3)]">{t.ticker}</span>
                </span>

                <svg width={58} height={20} viewBox="0 0 58 20" fill="none" aria-hidden="true">
                  {closes.length >= 2 && (
                    <path
                      d={sparkPath(closes, 58, 18)}
                      transform="translate(0,1)"
                      stroke={color}
                      strokeWidth={1.4}
                      strokeLinejoin="round"
                    />
                  )}
                </svg>

                <span className="num text-right text-[12px] font-semibold" style={{ color }}>
                  {closes.length >= 2 ? pct(change) : "—"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="border-t border-[var(--rule-2)] px-3.5 py-2 text-[11px] text-[var(--ink-3)]">
        {query ? `${visible.length}종목 검색됨` : `KOSPI200 ${tickers.length}종목`}
      </div>
    </aside>
  );
}
