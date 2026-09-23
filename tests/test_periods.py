"""주·월봉 재생성 SQL — D9 키 전환 (SPEC v2.6).

DB 없이 검증할 수 있는 것만 본다: 산식이 리샘플 규칙과 같은지, 키가 구간 시작일인지.
"""

from __future__ import annotations

import pytest

from pipeline.periods import UNITS, rebuild_sql


@pytest.mark.parametrize(("code", "unit"), [("W", "week"), ("M", "month")])
def test_sql_groups_by_the_period_start(code: str, unit: str) -> None:
    sql = rebuild_sql(code)
    assert f"date_trunc('{unit}', d)::date" in sql      # 키가 구간 시작일이다
    assert f"group by ticker, date_trunc('{unit}', d)" in sql
    assert f"'{code}'" in sql


@pytest.mark.parametrize("code", ["W", "M"])
def test_sql_matches_the_resample_rules(code: str) -> None:
    """시가=첫 봉, 종가=마지막 봉, 고저=최고·최저, 거래량=합계 (SPEC §5)."""
    sql = rebuild_sql(code)
    assert "(array_agg(o order by d asc))[1]" in sql
    assert "(array_agg(c order by d desc))[1]" in sql
    assert "max(h)" in sql and "min(l)" in sql
    assert "sum(v)" in sql


@pytest.mark.parametrize("code", ["W", "M"])
def test_amount_is_null_when_any_day_is_missing(code: str) -> None:
    """일부만 더한 거래대금은 사실이 아니다 — 구간에 NULL이 있으면 NULL로 둔다."""
    assert "count(*) filter (where a is null) > 0 then null" in rebuild_sql(code)


@pytest.mark.parametrize("code", ["W", "M"])
def test_source_is_daily_bars_only(code: str) -> None:
    assert "where timeframe = 'D' and ticker = any(%s)" in rebuild_sql(code)


def test_units_cover_both_periods() -> None:
    assert UNITS == {"W": "week", "M": "month"}


def test_rebuild_is_chunked_by_ticker() -> None:
    """전 종목을 한 문장으로 돌리면 statement timeout에 걸린다 (2026-09-23 실측)."""
    from pipeline.periods import CHUNK

    assert 0 < CHUNK <= 500
    assert all("ticker = any(%s)" in rebuild_sql(code) for code in ("W", "M"))
