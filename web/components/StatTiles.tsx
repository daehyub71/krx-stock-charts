"use client";

/** 통계 타일 (DESIGN §5-E 확정 구성). */

import { periodStats } from "@/lib/indicators";
import { pct, volume, won } from "@/lib/format";
import { RANGE_LABEL, TIMEFRAME_LABEL, type Bar, type RangeKey, type Timeframe } from "@/lib/types";

export interface StatTilesProps {
  bars: readonly Bar[];
  timeframe: Timeframe;
  range: RangeKey;
}

export default function StatTiles({ bars, timeframe, range }: StatTilesProps) {
  const stats = periodStats(bars, timeframe);
  const last = bars.at(-1);

  return (
    <dl className="grid grid-cols-2 gap-px bg-[var(--rule-2)] md:grid-cols-5">
      <Tile
        label="기간 수익률"
        value={pct(stats.returnPct)}
        sub={RANGE_LABEL[range]}
        color={stats.returnPct >= 0 ? "var(--up)" : "var(--down)"}
      />
      <Tile
        label="기간 최고가"
        value={won(stats.high)}
        sub={last && stats.high ? `종가 대비 ${pct((last.c / stats.high - 1) * 100)}` : "—"}
      />
      <Tile
        label="기간 최저가"
        value={won(stats.low)}
        sub={last && stats.low ? `종가 대비 ${pct((last.c / stats.low - 1) * 100)}` : "—"}
      />
      <Tile
        label="평균 거래량"
        value={volume(stats.avgVolume)}
        sub={`${TIMEFRAME_LABEL[timeframe]} 기준`}
      />
      <Tile
        label="연율 변동성"
        value={`${stats.volatility.toFixed(1)}%`}
        sub="로그수익률 표준편차"
      />
    </dl>
  );
}

function Tile({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub: string;
  color?: string;
}) {
  return (
    <div className="bg-[var(--surface)] px-5 py-3.5">
      <dt className="text-[10px] font-semibold uppercase tracking-[0.11em] text-[var(--ink-3)]">
        {label}
      </dt>
      <dd
        className="num mt-1 text-[19px] font-semibold tracking-tight"
        style={color ? { color } : undefined}
      >
        {value}
      </dd>
      <dd className="mt-0.5 text-[11px] text-[var(--ink-3)]">{sub}</dd>
    </div>
  );
}
