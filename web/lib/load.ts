/**
 * Supabase 조회 계층 — `ksc_` 테이블을 화면이 쓰는 모양으로 읽어온다.
 *
 * 리샘플은 파이프라인이 이미 끝냈으므로(D4) 여기서는 고르고 자르기만 한다.
 */

import { fetchAllPages, PAGE_SIZE } from "@/lib/paginate";
import { BARS_TABLE, getSupabase, TICKERS_TABLE } from "@/lib/supabase";
import { warmupCount } from "@/lib/indicators";
import {
  RANGE_BARS,
  TIMEFRAME_CODE,
  type Bar,
  type RangeKey,
  type Ticker,
  type Timeframe,
} from "@/lib/types";

const BAR_COLUMNS = "d,o,h,l,c,v,a";

/**
 * 한 번의 `.in()` 조회에 넣을 티커 수 상한.
 *
 * supabase-js는 `.in()` 값을 **쿼리 문자열**에 넣는다. 전 종목 2,763개를 한 번에 보내면
 * URL이 약 19KB가 되어 서버가 **400 Bad Request**로 거절한다 (전 종목 확장 후 실제 발생).
 * 티커 하나가 약 7바이트이므로 300개면 2KB 남짓으로 안전하다.
 */
export const SPARKLINE_TICKER_CHUNK = 300;

/** 배열을 고정 크기 그룹으로 나눈다. */
export function chunk<T>(items: readonly T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/**
 * 종목 목록을 티커 오름차순으로 읽는다.
 *
 * 200종목이라 한 페이지에 들어가지만, KOSPI200이 확장되거나 KOSDAQ이 추가되면
 * 1000행을 넘길 수 있으므로 페이지네이션을 거쳐 읽는다.
 */
export async function loadTickers(): Promise<Ticker[]> {
  const sb = getSupabase();
  return fetchAllPages<Ticker>(() =>
    sb.from(TICKERS_TABLE).select("ticker,name,market,sector").order("ticker"),
  );
}

/**
 * 한 종목·한 주기의 봉을 표시 구간 + 워밍업 구간만큼 읽는다.
 *
 * **워밍업이 이 함수의 핵심이다.** 표시 구간만 읽으면 이동평균선 앞부분이 비는데,
 * 화면 버그처럼 보이지만 원인은 조회 범위에 있다. 최장 MA 주기만큼 더 읽어서
 * 계산에만 쓰고 화면에는 그리지 않는다.
 *
 * @returns `visible`은 화면에 그릴 봉, `withWarmup`은 지표 계산용 전체 봉.
 */
export async function loadBars(
  ticker: string,
  timeframe: Timeframe,
  range: RangeKey,
): Promise<{ visible: Bar[]; withWarmup: Bar[]; warmup: number }> {
  const sb = getSupabase();

  const perBar = timeframe === "daily" ? 1 : timeframe === "weekly" ? 5 : 21;
  const showCount = Math.max(3, Math.ceil(RANGE_BARS[range] / perBar));
  const warmup = warmupCount(timeframe);
  const need = showCount + warmup;

  // 최신부터 내림차순으로 need개를 읽고 뒤집는다 — 오래된 쪽부터 읽으면
  // 상장 초기 구간만 가져오게 된다.
  const rows = await fetchAllPages<Bar>(
    () =>
      sb
        .from(BARS_TABLE)
        .select(BAR_COLUMNS)
        .eq("ticker", ticker)
        .eq("timeframe", TIMEFRAME_CODE[timeframe])
        .order("d", { ascending: false }),
    need,
  );

  const withWarmup = rows.slice().reverse();
  const visible = withWarmup.slice(Math.max(0, withWarmup.length - showCount));

  return { visible, withWarmup, warmup: withWarmup.length - visible.length };
}

/**
 * 좌측 레일의 스파크라인용으로 여러 종목의 최근 종가를 읽는다.
 *
 * 200종목 × 최근 봉이면 1000행 상한을 넘기므로 페이지네이션이 필수다 —
 * 이걸 빠뜨리면 뒤쪽 종목의 스파크라인이 조용히 사라진다.
 */
export async function loadSparklines(
  tickers: readonly string[],
  timeframe: Timeframe = "weekly",
  barsPerTicker = 26,
): Promise<Map<string, number[]>> {
  if (tickers.length === 0) return new Map();

  const sb = getSupabase();
  const groups = chunk(tickers, SPARKLINE_TICKER_CHUNK);

  const pages = await Promise.all(
    groups.map((group) =>
      fetchAllPages<{ ticker: string; d: string; c: number }>(() =>
        sb
          .from(BARS_TABLE)
          .select("ticker,d,c")
          .eq("timeframe", TIMEFRAME_CODE[timeframe])
          .in("ticker", group as string[])
          .order("ticker")
          .order("d", { ascending: false }),
      ),
    ),
  );
  const rows = pages.flat();

  const out = new Map<string, number[]>();
  for (const r of rows) {
    const list = out.get(r.ticker);
    if (list === undefined) {
      out.set(r.ticker, [r.c]);
    } else if (list.length < barsPerTicker) {
      list.push(r.c);
    }
  }
  // 내림차순으로 모았으므로 뒤집어 시간 순서로 만든다
  for (const [k, v] of out) out.set(k, v.reverse());
  return out;
}

/** 데이터 기준일 등 실행 메타를 읽는다. */
export async function loadMeta(key: string): Promise<Record<string, unknown> | null> {
  const sb = getSupabase();
  const { data, error } = await sb
    .from("ksc_meta")
    .select("value")
    .eq("key", key)
    .maybeSingle();
  if (error) throw new Error(`메타 조회 실패: ${error.message}`);
  return (data?.value as Record<string, unknown>) ?? null;
}

export { PAGE_SIZE };
