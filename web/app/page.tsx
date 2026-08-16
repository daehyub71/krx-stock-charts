"use client";

/**
 * 시세판 메인 화면 (DESIGN §1 IA · §5 확정 레이아웃).
 *
 * 상태는 여기서만 들고, 컴포넌트는 받은 것을 그린다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import CandleChart from "@/components/CandleChart";
import DataTable from "@/components/DataTable";
import QuoteHeader from "@/components/QuoteHeader";
import StatTiles from "@/components/StatTiles";
import TickerRail from "@/components/TickerRail";
import {
  SPARKLINE_TICKER_CHUNK,
  loadBars,
  loadMeta,
  loadSparklines,
  loadTickers,
} from "@/lib/load";
import {
  RANGE_LABEL,
  TIMEFRAME_LABEL,
  TIMEFRAMES,
  type Bar,
  type RangeKey,
  type Ticker,
  type Timeframe,
} from "@/lib/types";

import type { VolumeMode } from "@/lib/chart";

const RANGES: RangeKey[] = ["3M", "6M", "1Y", "3Y"];
type View = "chart" | "table";

export default function Page() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [sparklines, setSparklines] = useState<Map<string, number[]>>(new Map());
  const [selected, setSelected] = useState("005930");
  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [range, setRange] = useState<RangeKey>("1Y");
  const [view, setView] = useState<View>("chart");
  const [volumeMode, setVolumeMode] = useState<VolumeMode>("volume");

  const [asOf, setAsOf] = useState("");
  const [error, setError] = useState("");

  // 조회 결과를 요청 키와 함께 보관한다. loading을 따로 세팅하지 않고
  // "보관된 키가 현재 선택과 다른가"로 파생시킨다 — effect 안에서 동기 setState를
  // 하지 않아도 되고, 종목을 바꿀 때 이전 데이터가 잠깐 비치는 일도 없다.
  const [loaded, setLoaded] = useState<{ key: string; bars: Bar[]; warmup: number } | null>(null);
  const requestKey = `${selected}|${timeframe}|${range}`;
  const loading = loaded?.key !== requestKey;
  const bars = loaded?.key === requestKey ? loaded.bars : [];
  const warmup = loaded?.key === requestKey ? loaded.warmup : 0;

  useEffect(() => {
    loadTickers()
      .then((list) => {
        setTickers(list);

        // 전 종목 2,763개의 스파크라인을 한 번에 받으면 약 7만 행이라 첫 화면이 20초 가까이 늦다.
        // 레일에 실제로 보이는 종목만 받는다 (아래 fillSparklines).
      })
      .catch((e: Error) => setError(e.message));
    loadMeta("backfill")
      .then((m) => setAsOf(String(m?.updated ?? "")))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let stale = false;
    loadBars(selected, timeframe, range)
      .then((r) => {
        if (!stale) setLoaded({ key: requestKey, bars: r.withWarmup, warmup: r.warmup });
      })
      .catch((e: Error) => {
        if (!stale) setError(e.message);
      });
    return () => {
      stale = true;
    };
  }, [selected, timeframe, range, requestKey]);

  // 이미 요청한 종목을 기억한다. state 갱신자 안에서 부수효과를 내면
  // React가 갱신자를 두 번 호출할 때 요청이 중복되고, 반환값이 그대로라 렌더도 안 된다.
  const requested = useRef(new Set<string>());

  /** 레일에 보이는 종목 중 아직 안 받은 것만 채운다. */
  const fillSparklines = useCallback((visible: string[]) => {
    const missing = visible
      .filter((t) => !requested.current.has(t))
      .slice(0, SPARKLINE_TICKER_CHUNK);
    if (missing.length === 0) return;

    for (const t of missing) requested.current.add(t);
    loadSparklines(missing)
      .then((more) => {
        if (more.size > 0) setSparklines((cur) => new Map([...cur, ...more]));
      })
      .catch(() => {
        for (const t of missing) requested.current.delete(t);
      });
  }, []);

  const toggleTheme = useCallback(() => {
    const root = document.documentElement;
    const stamped = root.getAttribute("data-theme");
    const isDark = stamped
      ? stamped === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.setAttribute("data-theme", isDark ? "light" : "dark");
  }, []);

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

  const meta = tickers.find((t) => t.ticker === selected);
  const visible = bars.slice(warmup);

  return (
    <div className="mx-auto max-w-[1320px] px-5">
      <header className="flex flex-wrap items-center gap-3 border-b border-[var(--rule)] py-4">
        <div className="grid h-7 w-7 place-items-center rounded-md bg-[var(--accent)]">
          <svg width={15} height={15} viewBox="0 0 17 17" fill="none" aria-hidden="true">
            <path
              d="M2 12.5V14M6 7v7M10 9.5V14M14 3v11"
              stroke="#FFFEFB"
              strokeWidth={2}
              strokeLinecap="round"
            />
            <path
              d="M2 9.5 6 4l4 3.5L15 2"
              stroke="#FFFEFB"
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={0.62}
            />
          </svg>
        </div>
        <h1 className="text-[15px] font-semibold tracking-tight">시세판</h1>
        <span className="text-[12px] text-[var(--ink-3)]">KOSPI·KOSDAQ 전 종목 · 3년 일·주·월봉</span>

        <div className="ml-auto flex items-center gap-2">
          {asOf && (
            <span className="num rounded-full border border-[var(--rule)] bg-[var(--inset)] px-2.5 py-1 text-[11px] text-[var(--ink-2)]">
              {asOf} 종가 기준
            </span>
          )}
          <button
            type="button"
            onClick={toggleTheme}
            className="rounded-md border border-[var(--rule)] bg-[var(--surface)] px-2.5 py-1 text-[12px] text-[var(--ink-2)] hover:border-[var(--ink-3)] hover:text-[var(--ink)]"
          >
            테마 전환
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 items-start gap-5 py-5 md:grid-cols-[268px_minmax(0,1fr)]">
        <TickerRail
          tickers={tickers}
          sparklines={sparklines}
          selected={selected}
          onSelect={setSelected}
          onVisibleChange={fillSparklines}
        />

        <main className="flex min-w-0 flex-col gap-4">
          <section className="overflow-hidden rounded-xl border border-[var(--rule)] bg-[var(--surface)]">
            <QuoteHeader ticker={selected} meta={meta} bars={visible} />

            <div className="flex flex-wrap items-center gap-2.5 border-y border-[var(--rule-2)] px-5 py-3">
              <span className="text-[11px] text-[var(--ink-3)]">봉</span>
              <Segmented
                label="봉 주기"
                options={TIMEFRAMES.map((tf) => ({ value: tf, label: TIMEFRAME_LABEL[tf] }))}
                value={timeframe}
                onChange={setTimeframe}
              />
              <span className="ml-2 text-[11px] text-[var(--ink-3)]">기간</span>
              <Segmented
                label="조회 기간"
                options={RANGES.map((r) => ({ value: r, label: RANGE_LABEL[r] }))}
                value={range}
                onChange={setRange}
              />
              <span className="ml-2 text-[11px] text-[var(--ink-3)]">하단</span>
              <Segmented
                label="하단 지표"
                options={[
                  { value: "volume" as VolumeMode, label: "거래량" },
                  { value: "amount" as VolumeMode, label: "거래대금" },
                ]}
                value={volumeMode}
                onChange={setVolumeMode}
              />
              <div className="ml-auto">
                <Segmented
                  label="보기 방식"
                  options={[
                    { value: "chart" as View, label: "차트" },
                    { value: "table" as View, label: "표" },
                  ]}
                  value={view}
                  onChange={setView}
                />
              </div>
            </div>

            {view === "chart" ? (
              loading || visible.length === 0 ? (
                <div className="grid h-[420px] place-items-center text-[13px] text-[var(--ink-3)]">
                  {loading ? "불러오는 중…" : "표시할 봉이 없습니다"}
                </div>
              ) : (
                <CandleChart
                  bars={bars}
                  warmup={warmup}
                  timeframe={timeframe}
                  volumeMode={volumeMode}
                />
              )
            ) : (
              <div className="px-5 py-4 text-[12.5px] text-[var(--ink-3)]">
                아래 표에서 같은 데이터를 확인할 수 있습니다.
              </div>
            )}

            <StatTiles bars={visible} timeframe={timeframe} range={range} />
          </section>

          {view === "table" && <DataTable bars={visible} timeframe={timeframe} />}
        </main>
      </div>
    </div>
  );
}

function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex gap-0.5 rounded-lg border border-[var(--rule)] bg-[var(--inset)] p-0.5"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium ${
            o.value === value
              ? "bg-[var(--surface)] text-[var(--ink)] shadow-sm"
              : "text-[var(--ink-2)] hover:text-[var(--ink)]"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
