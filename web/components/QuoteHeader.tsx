"use client";

/** 종목 헤더 — 종목명·티커·시장·업종·현재가·등락 (DESIGN §1 IA). */

import { changeOf, pct, won } from "@/lib/format";
import type { Bar, Ticker } from "@/lib/types";

export interface QuoteHeaderProps {
  ticker: string;
  meta?: Ticker;
  bars: readonly Bar[];
}

export default function QuoteHeader({ ticker, meta, bars }: QuoteHeaderProps) {
  const last = bars.at(-1);
  const change = changeOf(last?.c ?? 0, bars.at(-2)?.c ?? null);
  const color = change.direction === "down" ? "var(--down)" : "var(--up)";

  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-3 p-5">
      <div>
        <h2 className="text-[21px] font-semibold tracking-tight">{meta?.name ?? "—"}</h2>
        <div className="mt-1 flex items-center gap-2 text-[12px] text-[var(--ink-2)]">
          <span className="num">{ticker}</span>
          {meta && (
            <>
              <Chip>{meta.market}</Chip>
              {meta.sector && <Chip>{meta.sector}</Chip>}
            </>
          )}
        </div>
      </div>

      <div className="ml-auto flex items-baseline gap-3" style={{ color }}>
        <span className="num text-[30px] font-semibold leading-none">
          {last ? won(last.c) : "—"}
        </span>
        <span className="num text-[14px] font-semibold">
          {change.direction === "down" ? "▼" : "▲"} {won(Math.abs(change.abs))}{" "}
          <span className="font-medium opacity-85">({pct(change.pct)})</span>
        </span>
      </div>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-[var(--rule)] bg-[var(--inset)] px-1.5 text-[10.5px]">
      {children}
    </span>
  );
}
