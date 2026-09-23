"""주·월봉 전량 재생성 — D9(봉 키 = 구간 시작일) 전환용 (SPEC v2.6).

키 정의가 바뀌면 기존 행의 `d`가 전부 달라진다. 덮어쓸 수 없으므로 **지우고 다시 만든다**.
덤으로 D9 이전에 쌓인 유령 부분봉도 이때 사라진다 — (종목, 월) 5,534건이 2행 이상이었다.

REST로 하지 않는다. 60만 행을 왕복시키면 요청이 수천 건이고, 집계는 DB가 훨씬 잘한다.
리샘플 규칙(`resample.py`)과 같은 산식을 SQL로 적는다.

**종목 묶음으로 쪼갠다.** 전 종목을 한 문장으로 돌리면 Supabase의 statement timeout에 걸린다
(2026-09-23 실측). 묶음마다 커밋하므로 중간에 끊겨도 다시 돌리면 이어서 끝난다 — 묶음 단위로
지우고 다시 넣기 때문에 같은 묶음을 두 번 처리해도 결과가 같다.

| 값 | 산식 |
|---|---|
| 날짜 | `date_trunc('week'|'month', d)` — 주는 월요일, 달은 1일 |
| 시가 | 구간 첫 거래일의 `o` |
| 종가 | 구간 마지막 거래일의 `c` |
| 고가·저가 | 구간 `max(h)` · `min(l)` |
| 거래량 | `sum(v)` |
| 거래대금 | 구간에 NULL이 하나라도 있으면 NULL, 아니면 `sum(a)` |
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

UNITS = {"W": "week", "M": "month"}
CHUNK = 200          # 한 문장이 다루는 종목 수 (실측: 전 종목 한 번에는 타임아웃)


@dataclass
class RebuildResult:
    """재생성 결과."""

    deleted: dict[str, int]
    inserted: dict[str, int]


def _connect() -> Any:
    """psycopg 연결을 연다 (일회성 대량 작업 — `amount.py`와 같은 이유)."""
    import psycopg

    dsn = os.getenv("SUPABASE_DATABASE_URL")
    if not dsn:
        raise RuntimeError("SUPABASE_DATABASE_URL 이 없다. .env를 확인하라.")
    return psycopg.connect(dsn, connect_timeout=60)


def rebuild_sql(code: str) -> str:
    """한 주기의 재생성 SQL. 리샘플 규칙(`resample._fold`)과 같은 산식이다."""
    unit = UNITS[code]
    return f"""
        insert into ksc_bars (ticker, timeframe, d, o, h, l, c, v, a)
        select ticker,
               '{code}',
               date_trunc('{unit}', d)::date,
               (array_agg(o order by d asc))[1],
               max(h),
               min(l),
               (array_agg(c order by d desc))[1],
               sum(v),
               case when count(*) filter (where a is null) > 0 then null else sum(a) end
        from ksc_bars
        where timeframe = 'D' and ticker = any(%s)
        group by ticker, date_trunc('{unit}', d)
    """


def rebuild_periods(codes: tuple[str, ...] = ("W", "M"), progress: bool = True) -> RebuildResult:
    """주·월봉을 지우고 일봉에서 다시 만든다.

    Args:
        codes: 다시 만들 주기 (`W` · `M`).
        progress: 진행 상황을 찍을 것인가.

    Returns:
        주기별 삭제·삽입 행 수.
    """
    deleted = dict.fromkeys(codes, 0)
    inserted = dict.fromkeys(codes, 0)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct ticker from ksc_bars where timeframe = 'D' order by ticker")
            tickers = [str(r[0]) for r in cur.fetchall()]
        conn.commit()
        if progress:
            print(f"  대상 {len(tickers):,}종목 · {CHUNK}종목씩")
        for start in range(0, len(tickers), CHUNK):
            chunk = tickers[start : start + CHUNK]
            for code in codes:
                with conn.cursor() as cur:
                    cur.execute(
                        "delete from ksc_bars where timeframe = %s and ticker = any(%s)",
                        (code, chunk),
                    )
                    deleted[code] += int(cur.rowcount)
                    cur.execute(rebuild_sql(code), (chunk,))
                    inserted[code] += int(cur.rowcount)
                conn.commit()
            if progress:
                done = min(start + CHUNK, len(tickers))
                print(f"  {done:,}/{len(tickers):,}종목 — "
                      + " · ".join(f"{c} {inserted[c]:,}행" for c in codes), flush=True)
    finally:
        conn.close()
    return RebuildResult(deleted=deleted, inserted=inserted)
