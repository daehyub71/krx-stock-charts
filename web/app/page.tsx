"use client";

/**
 * 시세판 메인 화면 (DESIGN §1 IA).
 *
 * M3 범위: 종목 목록·검색·선택까지. 차트는 M4에서 lightweight-charts로 붙인다.
 */

import { useEffect, useState } from "react";
import TickerRail from "@/components/TickerRail";
import { loadBars, loadMeta, loadSparklines, loadTickers } from "@/lib/load";
import { periodStats } from "@/lib/indicators";
import { changeOf, pct, volume, won } from "@/lib/format";
import {
  RANGE_LABEL,
  TIMEFRAME_LABEL,
  TIMEFRAMES,
  type Bar,
  type RangeKey,
  type Ticker,
  type Timeframe,
} from "@/lib/types";

const RANGES: RangeKey[] = ["3M", "6M", "1Y", "3Y"];

export default function Page() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [sparklines, setSparklines] = useState<Map<string, number[]>>(new Map());
  const [selected, setSelected] = useState("005930");
  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [range, setRange] = useState<RangeKey>("1Y");
  const [bars, setBars] = useState<Bar[]>([]);
  const [asOf, setAsOf] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    loadTickers()
      .then(async (list) => {
        setTickers(list);
        setSparklines(await loadSparklines(list.map((t) => t.ticker)));
      })
      .catch((e: Error) => setError(e.message));
    loadMeta("backfill")
      .then((m) => setAsOf(String(m?.updated ?? "")))
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadBars(selected, timeframe, range)
      .then((r) => setBars(r.visible))
      .catch((e: Error) => setError(e.message));
  }, [selected, timeframe, range]);

  const meta = tickers.find((t) => t.ticker === selected);
  const last = bars.at(-1);
  const change = changeOf(last?.c ?? 0, bars.at(-2)?.c ?? null);
  const stats = periodStats(bars, timeframe);
  const changeColor = change.direction === "down" ? "var(--down)" : "var(--up)";

  if (error) {
    return (
      <main className="mx-auto max-w-md p-10">
        <h1 className="text-lg font-semibold">데이터를 불러오지 못했습니다</h1>
        <p className="mt-2 text-sm text-[var(--ink-2)]">{error}</p>
        <p className="mt-4 text-sm text-[var(--ink-3)]">
          <code className="rounded bg-[var(--inset)] px-1.5 py-0.5">web/.env.local</code>에
          NEXT_PUBLIC_SUPABASE_URL과 NEXT_PUBLIC_SUPABASE_ANON_KEY가 있는지 확인하세요.
        </p>
      </main>
    );
  }

  return (
    <div className="mx-auto max-w-[1320px] px-5">
      <header className="flex items-center gap-3 border-b border-[var(--rule)] py-4">
        <div className="grid h-7 w-7 place-items-center rounded-md bg-[var(--accent)]">
          <svg width={15} height={15} viewBox="0 0 17 17" fill="none" aria-hidden="true">
            <path d="M2 12.5V14M6 7v7M10 9.5V14M14 3v11" stroke="#FFFEFB" strokeWidth={2} strokeLinecap="round" />
          </svg>
        </div>
        <h1 className="text-[15px] font-semibold tracking-tight">시세판</h1>
        <span className="text-[12px] text-[var(--ink-3)]">KOSPI200 · 3년 일·주·월봉</span>
        {asOf && (
          <span className="num ml-auto rounded-full border border-[var(--rule)] bg-[var(--inset)] px-2.5 py-1 text-[11px] text-[var(--ink-2)]">
            {asOf} 종가 기준
          </span>
        )}
      </header>

      <div className="grid grid-cols-1 gap-5 py-5 md:grid-cols-[268px_minmax(0,1fr)]">
        <TickerRail
          tickers={tickers}
          sparklines={sparklines}
          selected={selected}
          onSelect={setSelected}
        />

        <main className="min-w-0 rounded-xl border border-[var(--rule)] bg-[var(--surface)]">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-3 p-5">
            <div>
              <h2 className="text-[21px] font-semibold tracking-tight">{meta?.name ?? "—"}</h2>
              <div className="mt-1 flex items-center gap-2 text-[12px] text-[var(--ink-2)]">
                <span className="num">{selected}</span>
                {meta && (
                  <>
                    <span className="rounded border border-[var(--rule)] bg-[var(--inset)] px-1.5 text-[10.5px]">
                      {meta.market}
                    </span>
                    <span className="rounded border border-[var(--rule)] bg-[var(--inset)] px-1.5 text-[10.5px]">
                      {meta.sector}
                    </span>
                  </>
                )}
              </div>
            </div>
            <div className="ml-auto flex items-baseline gap-3" style={{ color: changeColor }}>
              <span className="num text-[30px] font-semibold leading-none">
                {last ? won(last.c) : "—"}
              </span>
              <span className="num text-[14px] font-semibold">
                {change.direction === "down" ? "▼" : "▲"} {won(Math.abs(change.abs))} ({pct(change.pct)})
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5 border-y border-[var(--rule-2)] px-5 py-3">
            <span className="text-[11px] text-[var(--ink-3)]">봉</span>
            <Segmented
              options={TIMEFRAMES.map((tf) => ({ value: tf, label: TIMEFRAME_LABEL[tf] }))}
              value={timeframe}
              onChange={setTimeframe}
            />
            <span className="ml-2 text-[11px] text-[var(--ink-3)]">기간</span>
            <Segmented
              options={RANGES.map((r) => ({ value: r, label: RANGE_LABEL[r] }))}
              value={range}
              onChange={setRange}
            />
          </div>

          <div className="grid place-items-center border-b border-[var(--rule-2)] px-5 py-16 text-center">
            <p className="text-[13px] text-[var(--ink-3)]">
              캔들 차트는 M4에서 lightweight-charts로 붙입니다.
              <br />
              현재 {TIMEFRAME_LABEL[timeframe]} {bars.length}봉 조회됨
              {bars.length > 0 && ` (${bars[0].d} ~ ${bars.at(-1)!.d})`}
            </p>
          </div>

          <dl className="grid grid-cols-2 gap-px bg-[var(--rule-2)] md:grid-cols-5">
            <Tile label="기간 수익률" value={pct(stats.returnPct)} sub={RANGE_LABEL[range]}
              color={stats.returnPct >= 0 ? "var(--up)" : "var(--down)"} />
            <Tile label="기간 최고가" value={won(stats.high)} sub={`종가 대비 ${last ? pct((last.c / stats.high - 1) * 100) : "—"}`} />
            <Tile label="기간 최저가" value={won(stats.low)} sub={`종가 대비 ${last ? pct((last.c / stats.low - 1) * 100) : "—"}`} />
            <Tile label="평균 거래량" value={volume(stats.avgVolume)} sub={`${TIMEFRAME_LABEL[timeframe]} 기준`} />
            <Tile label="연율 변동성" value={`${stats.volatility.toFixed(1)}%`} sub="로그수익률 표준편차" />
          </dl>
        </main>
      </div>
    </div>
  );
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="group" className="inline-flex gap-0.5 rounded-lg border border-[var(--rule)] bg-[var(--inset)] p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium ${
            o.value === value
              ? "bg-[var(--surface)] text-[var(--ink)]"
              : "text-[var(--ink-2)] hover:text-[var(--ink)]"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Tile({ label, value, sub, color }: { label: string; value: string; sub: string; color?: string }) {
  return (
    <div className="bg-[var(--surface)] px-5 py-3.5">
      <dt className="text-[10px] font-semibold uppercase tracking-[0.11em] text-[var(--ink-3)]">{label}</dt>
      <dd className="num mt-1 text-[19px] font-semibold tracking-tight" style={color ? { color } : undefined}>
        {value}
      </dd>
      <dd className="mt-0.5 text-[11px] text-[var(--ink-3)]">{sub}</dd>
    </div>
  );
}
