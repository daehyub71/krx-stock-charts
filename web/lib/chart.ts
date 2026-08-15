/**
 * 봉 데이터를 lightweight-charts가 받는 모양으로 바꾸는 순수 함수들.
 *
 * 차트 컴포넌트에서 분리한 이유는 테스트 때문이다 — 캔버스를 띄우지 않고
 * 변환 규칙만 검증할 수 있다.
 */

import { sma } from "@/lib/indicators";
import { MA_PERIODS, type Bar, type Timeframe } from "@/lib/types";

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumeBar {
  time: string;
  value: number;
  color: string;
}

export interface LinePoint {
  time: string;
  value: number;
}

export interface MaLine {
  period: number;
  label: string;
  color: string;
  points: LinePoint[];
  /** 범례에 표시할 마지막 값. 계산할 데이터가 부족하면 null. */
  latest: number | null;
}

/** 캔들 시리즈 데이터로 변환한다. */
export function toCandles(bars: readonly Bar[]): Candle[] {
  return bars.map((b) => ({
    time: b.d,
    open: b.o,
    high: b.h,
    low: b.l,
    close: b.c,
  }));
}

/**
 * 거래량 히스토그램으로 변환한다.
 *
 * 색은 캔들 몸통과 같은 규칙을 쓴다 — 종가가 시가 이상이면 상승색.
 * 보합(종가 = 시가)을 상승으로 두는 것도 캔들과 맞춘 것이다.
 */
export function toVolumeBars(
  bars: readonly Bar[],
  palette: { up: string; down: string },
): VolumeBar[] {
  return bars.map((b) => ({
    time: b.d,
    value: b.v,
    color: b.c >= b.o ? palette.up : palette.down,
  }));
}

/**
 * 봉과 같은 길이의 값 배열을 선 데이터로 바꾼다.
 *
 * null인 구간은 점을 만들지 않는다 — 이동평균의 앞부분이 여기에 해당한다.
 */
export function toLinePoints(
  bars: readonly Bar[],
  values: readonly (number | null)[],
): LinePoint[] {
  const out: LinePoint[] = [];
  const n = Math.min(bars.length, values.length);
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (v !== null) out.push({ time: bars[i].d, value: v });
  }
  return out;
}

/**
 * 주기에 맞는 이동평균선들을 만든다.
 *
 * `bars`는 **워밍업 구간을 포함한** 전체 봉이고, `warmup`은 그중 화면에 그리지 않을
 * 앞부분의 개수다. 이동평균은 전체로 계산한 뒤 워밍업 구간만 잘라낸다 —
 * 그래야 표시 구간의 첫 봉부터 선이 그려진다.
 *
 * @param bars 워밍업 포함 전체 봉 (날짜 오름차순).
 * @param timeframe 주기 — MA 기간 집합을 고른다.
 * @param warmup 화면에서 잘라낼 앞부분 봉 수.
 * @param colors MA 색상. 고정 순서로 배정한다.
 */
export function maSeries(
  bars: readonly Bar[],
  timeframe: Timeframe,
  warmup: number,
  colors: readonly string[],
): MaLine[] {
  return MA_PERIODS[timeframe].map((period, i) => {
    const values = sma(bars, period);
    const visibleBars = bars.slice(warmup);
    const visibleValues = values.slice(warmup);

    const defined = values.filter((v): v is number => v !== null);

    return {
      period,
      label: `MA${period}`,
      color: colors[i % colors.length],
      points: toLinePoints(visibleBars, visibleValues),
      latest: defined.length > 0 ? defined[defined.length - 1] : null,
    };
  });
}

/**
 * CSS 커스텀 프로퍼티에서 색을 읽는다.
 *
 * lightweight-charts는 캔버스에 그리므로 `var(--up)` 같은 값을 그대로 줄 수 없다.
 * 실제 색 문자열로 풀어서 넘겨야 하고, 테마가 바뀌면 다시 읽어 시리즈에 적용해야 한다.
 */
export function readToken(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export interface ChartPalette {
  up: string;
  down: string;
  ink: string;
  ink3: string;
  rule: string;
  rule2: string;
  surface: string;
  ma: string[];
}

/** 현재 테마의 차트 색상 묶음을 읽는다. */
export function readChartPalette(): ChartPalette {
  return {
    up: readToken("--up", "#c8372d"),
    down: readToken("--down", "#2e6fbf"),
    ink: readToken("--ink", "#1e1d1a"),
    ink3: readToken("--ink-3", "#8b8578"),
    rule: readToken("--rule", "#e4e1d7"),
    rule2: readToken("--rule-2", "#efede5"),
    surface: readToken("--surface", "#fffefb"),
    ma: [
      readToken("--ma-1", "#a87f1c"),
      readToken("--ma-2", "#0e96ae"),
      readToken("--ma-3", "#8a5ad0"),
      readToken("--ma-4", "#b0435e"),
    ],
  };
}

/**
 * 시간축 눈금 라벨.
 *
 * 기본 포매터는 연·월·일 눈금을 각각 다른 형식으로 찍어서
 * "9월 · 10월 · **7일** · 2026년"처럼 축이 뒤섞여 읽힌다.
 * 일 눈금에도 월을 붙여 어느 시점인지 한눈에 들어오게 한다.
 *
 * @param time lightweight-charts가 주는 시각 ("YYYY-MM-DD" 문자열 또는 UTC 초).
 * @param tickType 0=연, 1=월, 2=일, 그 외는 시각.
 */
export function formatTickMark(time: unknown, tickType: number): string {
  const iso =
    typeof time === "string"
      ? time
      : new Date((time as number) * 1000).toISOString().slice(0, 10);
  const [year, month, day] = iso.split("-");

  if (tickType === 0) return `${year}년`;
  if (tickType === 1) return `${Number(month)}월`;
  return `${Number(month)}/${Number(day)}`;
}
