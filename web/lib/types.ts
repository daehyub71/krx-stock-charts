/**
 * 파이프라인 `pipeline/models.py`와 1:1로 대응하는 타입 계약.
 * 두 층은 이 모양의 데이터로만 만난다 (PLAN §1).
 *
 * 이 파일을 고칠 때는 `models.py`와 `supabase/schema.sql`도 함께 본다.
 */

/** 봉 주기. Supabase `ksc_bars.timeframe` 값과 같다. */
export type Timeframe = "daily" | "weekly" | "monthly";

export const TIMEFRAMES: readonly Timeframe[] = ["daily", "weekly", "monthly"];

/** 주기별 한글 이름 (화면 표시용). */
export const TIMEFRAME_LABEL: Record<Timeframe, string> = {
  daily: "일봉",
  weekly: "주봉",
  monthly: "월봉",
};

/** 종목 메타 (`ksc_tickers`). */
export interface Ticker {
  /** 6자리 영숫자 코드. 숫자만이 아니다 — 0126Z0 같은 코드가 실재한다. */
  ticker: string;
  name: string;
  market: string;
  sector: string;
}

/**
 * 하나의 봉 (`ksc_bars`).
 *
 * 주봉·월봉의 `d`는 해당 구간의 마지막 거래일이다.
 * `a`(거래대금)는 종목축으로 백필한 봉에는 없으므로 null일 수 있다.
 */
export interface Bar {
  /** 거래일 "YYYY-MM-DD". */
  d: string;
  /** 시가 (원). */
  o: number;
  /** 고가 (원). */
  h: number;
  /** 저가 (원). */
  l: number;
  /** 종가 (원). */
  c: number;
  /** 거래량 (주). */
  v: number;
  /** 거래대금 (원). 백필분은 null. */
  a: number | null;
}

/** 차트 표시 기간 프리셋. */
export type RangeKey = "3M" | "6M" | "1Y" | "3Y";

/** 기간별로 표시할 일봉 개수 (거래일 기준 근사). */
export const RANGE_BARS: Record<RangeKey, number> = {
  "3M": 62,
  "6M": 123,
  "1Y": 246,
  "3Y": 760,
};

export const RANGE_LABEL: Record<RangeKey, string> = {
  "3M": "3개월",
  "6M": "6개월",
  "1Y": "1년",
  "3Y": "3년",
};

/**
 * 주기별 이동평균 기간.
 *
 * 주기가 길수록 짧은 기간을 쓴다 — 월봉에 MA120은 10년치라 의미가 없다.
 */
export const MA_PERIODS: Record<Timeframe, readonly number[]> = {
  daily: [5, 20, 60, 120],
  weekly: [5, 20, 60],
  monthly: [3, 12],
};
