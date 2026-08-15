/**
 * 지표 계산 — 이동평균과 기간 통계.
 *
 * 리샘플은 파이프라인이 맡으므로(D4) 표현 층에 남은 계산은 이것뿐이다.
 */

import { MA_PERIODS, type Bar, type Timeframe } from "@/lib/types";

/** 주기별 연율화 계수 (연간 거래일/주/월 수). */
const PERIODS_PER_YEAR: Record<Timeframe, number> = {
  daily: 246,
  weekly: 52,
  monthly: 12,
};

/**
 * 단순이동평균을 계산한다.
 *
 * 앞의 `period - 1`개는 계산할 데이터가 없으므로 null이다.
 * 표시 구간의 첫 봉부터 선이 그려지려면 호출 전에 워밍업 구간을 붙여 읽어야 한다
 * (`warmupCount` 참조).
 *
 * @param bars 봉 리스트 (날짜 오름차순).
 * @param period 이동평균 기간.
 * @returns 각 봉에 대응하는 평균값. 계산 불가 구간은 null.
 */
export function sma(bars: readonly Bar[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let sum = 0;

  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].c;
    if (i >= period) sum -= bars[i - period].c;
    if (i >= period - 1) out[i] = sum / period;
  }

  return out;
}

/**
 * 해당 주기에서 MA선이 첫 봉부터 그려지려면 앞에 더 읽어야 하는 봉 수.
 *
 * 표시 구간만 읽으면 이동평균선 앞부분이 빈다 — 화면 버그처럼 보이지만
 * 원인은 조회 범위에 있다. 조회 시 `표시개수 + warmupCount(tf)`만큼 읽는다.
 */
export function warmupCount(timeframe: Timeframe): number {
  return Math.max(...MA_PERIODS[timeframe]);
}

export interface PeriodStats {
  /** 첫 봉 시가 대비 마지막 봉 종가의 등락률 (%). */
  returnPct: number;
  /** 기간 최고가. */
  high: number;
  /** 기간 최저가. */
  low: number;
  /** 봉당 평균 거래량. */
  avgVolume: number;
  /** 로그수익률 표준편차를 연율화한 변동성 (%). */
  volatility: number;
}

/**
 * 표시 구간의 요약 통계를 계산한다 (DESIGN §5-E 통계 타일).
 *
 * @param bars 표시 구간의 봉 (워밍업 구간을 제외한 것).
 * @param timeframe 변동성 연율화에 쓸 주기.
 */
export function periodStats(bars: readonly Bar[], timeframe: Timeframe): PeriodStats {
  if (bars.length === 0) {
    return { returnPct: 0, high: 0, low: 0, avgVolume: 0, volatility: 0 };
  }

  const first = bars[0];
  const last = bars[bars.length - 1];

  let high = -Infinity;
  let low = Infinity;
  let volumeSum = 0;
  for (const b of bars) {
    if (b.h > high) high = b.h;
    if (b.l < low) low = b.l;
    volumeSum += b.v;
  }

  const returns: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    returns.push(Math.log(bars[i].c / bars[i - 1].c));
  }

  let volatility = 0;
  if (returns.length > 0) {
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const variance =
      returns.reduce((a, b) => a + (b - mean) ** 2, 0) / returns.length;
    volatility = Math.sqrt(variance) * Math.sqrt(PERIODS_PER_YEAR[timeframe]) * 100;
  }

  return {
    returnPct: first.o === 0 ? 0 : (last.c / first.o - 1) * 100,
    high,
    low,
    avgVolume: volumeSum / bars.length,
    volatility,
  };
}
