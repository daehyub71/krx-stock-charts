"""거래대금(`ksc_bars.a`) 소급 채우기.

거래대금은 **날짜축 조회에만** 있다. 백필은 종목축으로 돌았으므로 과거분이 전부 NULL이다
(일일 갱신분만 채워져 있다). 이 모듈이 3년치를 날짜축으로 다시 훑어 메운다.

**REST로 갱신하지 않는다.** 190만 행을 upsert하면 요청이 수천 건이 되고 행 전체를 다시 쓴다.
임시 테이블에 COPY로 부어 넣고 `UPDATE ... FROM`으로 한 번에 반영한다 — 컬럼 하나만 건드린다.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta

from pipeline import krx_client


@dataclass
class FillResult:
    """채우기 실행 결과."""

    trading_days: int = 0
    holidays: int = 0
    fetched_rows: int = 0
    updated_daily: int = 0
    updated_weekly: int = 0
    updated_monthly: int = 0
    failed_dates: list[str] = field(default_factory=list)


def trading_day_candidates(start: date, end: date) -> Iterator[str]:
    """주말을 뺀 날짜를 오름차순으로 낸다.

    공휴일은 KRX 응답이 비는 것으로 판별한다 — 달력을 따로 들고 있지 않는다.
    """
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day.strftime("%Y%m%d")
        day += timedelta(days=1)


def month_chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    """기간을 달 단위로 쪼갠다.

    한 번에 190만 행을 메모리에 올리지 않기 위해서다. 진행 상황도 달 단위로 보인다.
    """
    cursor = start.replace(day=1)
    while cursor <= end:
        nxt = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(cursor, start), min(nxt - timedelta(days=1), end)
        cursor = nxt


def _connect() -> object:
    """psycopg 연결을 연다.

    거래대금 채우기는 **일회성 소급 작업**이라 psycopg를 여기서만 쓴다.
    평상시 파이프라인은 supabase-py(REST)로 돌아간다.
    """
    import psycopg

    dsn = os.getenv("SUPABASE_DATABASE_URL")
    if not dsn:
        raise RuntimeError("SUPABASE_DATABASE_URL 이 없다. .env를 확인하라.")
    return psycopg.connect(dsn, connect_timeout=60)


def fill_amounts(start: date, end: date, progress: bool = True) -> FillResult:
    """구간의 일봉 거래대금을 채우고, 주봉·월봉을 합계로 다시 계산한다.

    Args:
        start: 시작일.
        end: 종료일.
        progress: 진행 상황 출력 여부.

    Returns:
        실행 결과 요약.
    """
    result = FillResult()
    conn = _connect()

    try:
        with conn:  # type: ignore[attr-defined]
            with conn.cursor() as cur:  # type: ignore[attr-defined]
                cur.execute("select ticker from ksc_tickers")
                universe = {r[0] for r in cur.fetchall()}

            for chunk_start, chunk_end in month_chunks(start, end):
                rows: list[tuple[str, str, int]] = []

                for day in trading_day_candidates(chunk_start, chunk_end):
                    try:
                        bars = krx_client.get_ohlcv_by_date(day)
                    except krx_client.KrxError:
                        result.failed_dates.append(day)
                        continue

                    if not bars:
                        result.holidays += 1
                        continue

                    result.trading_days += 1
                    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
                    for ticker, bar in bars.items():
                        # `if bar.amount:` 로 쓰면 **거래대금 0이 걸러진다.**
                        # 거래가 없던 날(거래정지)의 거래대금은 "모름"이 아니라 0이다.
                        # NULL로 남기면 평균 계산이 통째로 null이 되어버린다.
                        if ticker in universe and bar.amount is not None:
                            rows.append((ticker, iso, bar.amount))

                if not rows:
                    continue

                result.fetched_rows += len(rows)
                updated = _apply_daily(conn, rows)
                result.updated_daily += updated

                if progress:
                    print(
                        f"  {chunk_start:%Y-%m}  조회 {len(rows):>6,}행 → 갱신 {updated:>6,}행",
                        flush=True,
                    )

            # 일봉이 다 채워진 뒤에야 주봉·월봉 합계가 의미를 가진다.
            result.updated_weekly = _recompute_period(conn, "W", "week")
            result.updated_monthly = _recompute_period(conn, "M", "month")
    finally:
        conn.close()  # type: ignore[attr-defined]

    return result


def _apply_daily(conn: object, rows: list[tuple[str, str, int]]) -> int:
    """임시 테이블에 COPY한 뒤 한 번의 UPDATE로 반영한다."""
    buffer = io.StringIO()
    for ticker, iso, amount in rows:
        buffer.write(f"{ticker}\t{iso}\t{amount}\n")
    buffer.seek(0)

    with conn.cursor() as cur:  # type: ignore[attr-defined]
        cur.execute("create temp table _amt (ticker text, d date, a bigint) on commit drop")
        with cur.copy("copy _amt (ticker, d, a) from stdin") as copy:
            copy.write(buffer.read())
        cur.execute("create index on _amt (ticker, d)")
        cur.execute(
            """update ksc_bars b set a = t.a
               from _amt t
               where b.ticker = t.ticker and b.timeframe = 'D' and b.d = t.d
                 and b.a is distinct from t.a"""
        )
        updated: int = cur.rowcount
    conn.commit()  # type: ignore[attr-defined]
    return updated


def _recompute_period(conn: object, code: str, unit: str) -> int:
    """주봉·월봉의 거래대금을 해당 구간 일봉의 합계로 다시 계산한다.

    구간에 NULL이 하나라도 있으면 합계도 NULL로 둔다 — 일부만 더한 값은 사실이 아니다.
    """
    with conn.cursor() as cur:  # type: ignore[attr-defined]
        cur.execute(
            f"""
            with agg as (
              select ticker,
                     max(d) as last_d,
                     case when count(*) filter (where a is null) > 0 then null
                          else sum(a) end as total
              from ksc_bars
              where timeframe = 'D'
              group by ticker, date_trunc('{unit}', d)
            )
            update ksc_bars b set a = agg.total
            from agg
            where b.ticker = agg.ticker and b.timeframe = %s and b.d = agg.last_d
              and b.a is distinct from agg.total
            """,
            (code,),
        )
        updated: int = cur.rowcount
    conn.commit()  # type: ignore[attr-defined]
    return updated
