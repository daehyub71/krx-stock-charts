/**
 * 화면 표시용 포맷터.
 *
 * DESIGN §3: 모든 숫자는 고정폭 서체 + tabular-nums로 그린다.
 * 여기서는 문자열만 만들고, 정렬은 CSS가 맡는다.
 */

const NF = new Intl.NumberFormat("ko-KR");

/** 원 단위 금액을 천 단위 구분 문자열로 만든다. */
export function won(value: number): string {
  return NF.format(Math.round(value));
}

/** 등락률을 부호가 붙은 백분율 문자열로 만든다 (0은 +로 표기). */
export function pct(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** 거래량을 억/만 단위로 줄여 표시한다. */
export function volume(value: number): string {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}억`;
  if (value >= 10_000) {
    const man = value / 10_000;
    return `${man >= 100 ? Math.round(man) : man.toFixed(1)}만`;
  }
  return NF.format(value);
}

/**
 * 거래대금을 조/억/만 단위로 줄여 표시한다.
 *
 * 거래량(주)과 달리 **가격대가 다른 종목끼리 비교할 수 있어** 유동성 판단에 쓸모가 있다.
 * 100원짜리 100만 주와 50만원짜리 100만 주는 거래량은 같지만 거래대금은 5천 배 차이다.
 *
 * @param value 원 단위 금액. 종목축으로 백필한 봉은 값이 없어 null이다.
 */
export function amount(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1_000_000_000_000) return `${(value / 1_000_000_000_000).toFixed(2)}조`;
  if (value >= 100_000_000) {
    const eok = value / 100_000_000;
    return `${eok >= 100 ? Math.round(eok) : eok.toFixed(1)}억`;
  }
  if (value >= 10_000) return `${NF.format(Math.round(value / 10_000))}만`;
  return NF.format(value);
}

export type Direction = "up" | "down" | "flat";

export interface Change {
  abs: number;
  pct: number;
  direction: Direction;
}

/**
 * 직전 종가 대비 변화를 계산한다.
 *
 * 직전 봉이 없으면(계열의 첫 봉) 0/flat을 돌려준다 — NaN이 화면에 새지 않도록.
 */
export function changeOf(close: number, previousClose: number | null): Change {
  if (previousClose === null || previousClose === 0) {
    return { abs: 0, pct: 0, direction: "flat" };
  }
  const abs = close - previousClose;
  return {
    abs,
    pct: (close / previousClose - 1) * 100,
    direction: abs > 0 ? "up" : abs < 0 ? "down" : "flat",
  };
}
