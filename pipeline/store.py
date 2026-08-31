"""Supabase 저장 계층 (SPEC D2 — 2026-08-15 정적 JSON에서 변경).

모든 테이블은 `ksc_` 접두어를 쓴다 — 같은 Supabase 프로젝트에 다른 서비스의
테이블이 함께 있기 때문이다.

쓰기는 전부 upsert다. 같은 데이터를 두 번 써도 행이 늘지 않으므로 파이프라인 재실행이
안전하다 (SPEC N1 멱등성).
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Protocol

from pipeline.models import TIMEFRAME_CODE, Bar, InvestorFlow, MarketCap, Ticker, Timeframe

TICKERS_TABLE = "ksc_tickers"
BARS_TABLE = "ksc_bars"
META_TABLE = "ksc_meta"

# Supabase REST는 요청 크기에 제한이 있어 대량 삽입을 나눠 보낸다.
DEFAULT_BATCH = 500

# Supabase REST가 한 응답에 담아주는 최대 행 수. 이보다 크게 요청해도 조용히 잘린다.
DEFAULT_PAGE = 1000


class SupabaseLike(Protocol):
    """테스트에서 가짜로 대체할 수 있도록 최소 인터페이스만 요구한다."""

    def table(self, name: str) -> Any: ...


def get_client() -> SupabaseLike:
    """환경 변수로 Supabase 클라이언트를 만든다.

    파이프라인은 service_role 키를 쓴다 — RLS를 우회해 쓰기가 가능하다.
    이 키는 서버·CI에서만 쓰며 웹 번들에 절대 넣지 않는다.

    Returns:
        Supabase 클라이언트.

    Raises:
        RuntimeError: 환경 변수가 없을 때.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY 가 없습니다. .env를 확인하세요."
        )

    from supabase import create_client

    return create_client(url, key)


def chunked(items: Sequence[Any], size: int) -> Iterator[list[Any]]:
    """시퀀스를 size 크기의 리스트로 나눈다.

    Args:
        items: 나눌 시퀀스.
        size: 청크 크기.

    Yields:
        최대 size 길이의 리스트. 마지막 청크는 더 짧을 수 있다.
    """
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def ticker_rows(tickers: Sequence[Ticker]) -> list[dict[str, str]]:
    """Ticker 리스트를 `ksc_tickers` 행으로 변환한다."""
    return [
        {"ticker": t.ticker, "name": t.name, "market": t.market, "sector": t.sector}
        for t in tickers
    ]


def bar_rows(ticker: str, timeframe: Timeframe, bars: Sequence[Bar]) -> list[dict[str, Any]]:
    """Bar 리스트를 `ksc_bars` 행으로 변환한다."""
    return [
        {
            "ticker": ticker,
            "timeframe": TIMEFRAME_CODE[timeframe],
            "d": b.date,
            "o": b.open,
            "h": b.high,
            "l": b.low,
            "c": b.close,
            "v": b.volume,
            "a": b.amount,
        }
        for b in bars
    ]


def upsert_tickers(
    client: SupabaseLike,
    tickers: Sequence[Ticker],
    batch_size: int = DEFAULT_BATCH,
) -> int:
    """종목 메타를 저장한다 (멱등).

    Args:
        client: Supabase 클라이언트.
        tickers: 저장할 종목.
        batch_size: 한 요청에 보낼 최대 행 수.

    Returns:
        저장한 행 수.
    """
    rows = ticker_rows(tickers)
    for batch in chunked(rows, batch_size):
        client.table(TICKERS_TABLE).upsert(batch, on_conflict="ticker").execute()
    return len(rows)


# `.in_()`은 쿼리 문자열에 들어간다. 한 번에 넣을 티커 수 상한.
# 2,700개를 그대로 넣었더니 URL이 길어져 PostgREST가 400을 돌려줬다 (2026-08-30 실장애).
# 웹(`web/lib/load.ts`)은 같은 이유로 300을 쓴다.
TICKER_FILTER_CHUNK = 300

INVESTOR_FLOWS_TABLE = "ksc_investor_flows"

# 얼마나 보관할지. 하위 프로젝트는 30일을 읽는다 — 넉넉히 두되 무한히 쌓지는 않는다.
# 2,700행/일 × 120일 ≈ 32만 행. 보존 기간이 없으면 1년에 100만 행이 된다.
RETENTION_DAYS = 120


def investor_flow_rows(
    flows: Mapping[str, InvestorFlow], day: date
) -> list[dict[str, Any]]:
    """`ksc_investor_flows` 행으로 편다 (SPEC F14).

    **None을 0으로 채우지 않는다.** 그 투자자 표에 종목이 없었다는 사실과
    순매수가 0원이었다는 사실은 다르다.

    Args:
        flows: {티커: InvestorFlow}.
        day: 거래일.

    Returns:
        티커 오름차순 행 목록.
    """
    iso = day.isoformat()
    return [
        {
            "d": iso,
            "ticker": ticker,
            "inst_net": f.inst_net,
            "foreign_net": f.foreign_net,
            "foreign_etc_net": f.foreign_etc_net,
            "indiv_net": f.indiv_net,
            "corp_etc_net": f.corp_etc_net,
        }
        for ticker, f in sorted(flows.items())
    ]


def upsert_investor_flows(
    client: SupabaseLike,
    flows: Mapping[str, InvestorFlow],
    day: date,
    batch_size: int = DEFAULT_BATCH,
) -> int:
    """투자자별 순매수를 저장한다 (멱등, SPEC F14).

    Args:
        client: Supabase 클라이언트.
        flows: {티커: InvestorFlow}.
        day: 거래일.
        batch_size: 한 요청에 보낼 최대 행 수.

    Returns:
        저장한 행 수.
    """
    rows = investor_flow_rows(flows, day)
    for batch in chunked(rows, batch_size):
        client.table(INVESTOR_FLOWS_TABLE).upsert(batch, on_conflict="d,ticker").execute()
    return len(rows)


def prune_investor_flows(
    client: SupabaseLike, today: date, keep_days: int = RETENTION_DAYS
) -> None:
    """보존 기간을 넘긴 행을 지운다 (SPEC F14).

    쌓기만 하면 1년에 100만 행이 된다. `ksc_bars`가 이미 2.4M행이다.

    Args:
        client: Supabase 클라이언트.
        today: 기준일.
        keep_days: 보관할 일수.
    """
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    client.table(INVESTOR_FLOWS_TABLE).delete().lt("d", cutoff).execute()


def market_cap_rows(
    tickers: Sequence[Ticker], caps: Mapping[str, MarketCap], basis: date
) -> list[dict[str, Any]]:
    """종목 메타 + 시가총액을 `ksc_tickers` 행으로 합친다 (SPEC F8).

    **메타를 함께 담아야 한다.** PostgREST의 upsert는 부분 갱신이 아니라 행 전체를 다시 쓰므로,
    시총 열만 보내면 `name`이 null이 되어 not-null 제약에 걸린다 (2026-08-29 실측).

    Args:
        tickers: DB에서 읽은 현재 종목 메타.
        caps: {티커: MarketCap}. 여기 없는 종목은 결과에서 빠진다.
        basis: 시총 기준일.

    Returns:
        티커 오름차순 행 목록. 시총이 있는 종목만.
    """
    return [
        {
            "ticker": t.ticker,
            "name": t.name,
            "market": t.market,
            "sector": t.sector,
            "mktcap": caps[t.ticker].mktcap,
            "list_shrs": caps[t.ticker].list_shrs,
            "mktcap_d": basis.isoformat(),
        }
        for t in sorted(tickers, key=lambda x: x.ticker)
        if t.ticker in caps
    ]


def upsert_market_caps(
    client: SupabaseLike,
    tickers: Sequence[Ticker],
    caps: Mapping[str, MarketCap],
    basis: date,
    batch_size: int = DEFAULT_BATCH,
) -> int:
    """시가총액·상장주식수를 저장한다 (멱등, SPEC F8).

    Args:
        client: Supabase 클라이언트.
        tickers: DB에서 읽은 현재 종목 메타 (upsert가 덮어쓰지 않게 함께 보낸다).
        caps: {티커: MarketCap}.
        basis: 시총 기준일.
        batch_size: 한 요청에 보낼 최대 행 수.

    Returns:
        저장한 행 수.
    """
    rows = market_cap_rows(tickers, caps, basis)
    for batch in chunked(rows, batch_size):
        client.table(TICKERS_TABLE).upsert(batch, on_conflict="ticker").execute()
    return len(rows)


def upsert_bars(
    client: SupabaseLike,
    ticker: str,
    timeframe: Timeframe,
    bars: Sequence[Bar],
    batch_size: int = DEFAULT_BATCH,
) -> int:
    """봉 데이터를 저장한다 (멱등).

    PK가 (ticker, timeframe, d)이므로 같은 날짜를 다시 쓰면 덮어써진다 —
    수정주가 소급 변경이나 진행 중인 주/월봉 재계산이 그대로 반영된다.

    Args:
        client: Supabase 클라이언트.
        ticker: 종목 코드.
        timeframe: "daily" | "weekly" | "monthly".
        bars: 저장할 봉.
        batch_size: 한 요청에 보낼 최대 행 수.

    Returns:
        저장한 행 수.
    """
    rows = bar_rows(ticker, timeframe, bars)
    for batch in chunked(rows, batch_size):
        client.table(BARS_TABLE).upsert(batch, on_conflict="ticker,timeframe,d").execute()
    return len(rows)


def upsert_bars_bulk(
    client: SupabaseLike,
    timeframe: Timeframe,
    items: Mapping[str, Sequence[Bar]],
    batch_size: int = DEFAULT_BATCH,
) -> int:
    """여러 종목의 봉을 **종목을 가로질러 묶어** 저장한다 (멱등).

    `upsert_bars`는 한 종목 안에서만 묶으므로 종목마다 요청이 나간다. 일일 갱신은
    종목당 봉이 하나라 그대로 2,700회가 되고, 주·월봉까지 더하면 약 8,000회다.
    워크플로 제한은 30분인데 그만큼이면 40~50분이 걸린다 — 거래일 실행이 매번
    잘린 진짜 이유였다 (2026-08-30 확인).

    Args:
        client: Supabase 클라이언트.
        timeframe: "daily" | "weekly" | "monthly".
        items: {티커: 봉 목록}.
        batch_size: 한 요청에 보낼 최대 행 수.

    Returns:
        저장한 행 수.
    """
    rows: list[dict[str, Any]] = []
    for ticker, bars in items.items():
        rows.extend(bar_rows(ticker, timeframe, bars))
    for batch in chunked(rows, batch_size):
        client.table(BARS_TABLE).upsert(batch, on_conflict="ticker,timeframe,d").execute()
    return len(rows)


def set_meta(client: SupabaseLike, key: str, value: dict[str, Any]) -> None:
    """실행 메타를 기록한다 (데이터 기준일·행 수 등).

    Args:
        client: Supabase 클라이언트.
        key: 메타 키 (예: "universe", "backfill").
        value: JSON 직렬화 가능한 값.
    """
    client.table(META_TABLE).upsert({"key": key, "value": value}, on_conflict="key").execute()


def fetch_daily_since(
    client: SupabaseLike,
    since: str,
    tickers: Sequence[str] | None = None,
    page: int = 1000,
    chunk: int = TICKER_FILTER_CHUNK,
) -> dict[str, list[Bar]]:
    """특정 날짜 이후의 일봉을 종목별로 읽는다.

    Supabase REST는 한 응답의 행 수에 상한이 있으므로 range로 페이지네이션한다.

    **티커 필터는 나눠 보낸다.** `.in_()`은 쿼리 문자열에 들어가므로 2,700개를 한 번에
    넣으면 URL이 길어져 PostgREST가 `400 Bad Request`를 돌려준다. 응답 본문이 JSON이
    아니라 supabase-py는 "JSON could not be generated"로 다시 감싸 원인이 드러나지 않는다.
    이 실패가 2026-08-18부터 매일 워크플로를 멈춰 세웠다 (08/28 일봉과 주·월봉 재계산이 빠졌다).

    Args:
        client: Supabase 클라이언트.
        since: 이 날짜 이상 ("YYYY-MM-DD").
        tickers: 대상 종목. None이면 전체.
        page: 페이지 크기.
        chunk: 한 요청에 넣을 티커 수 상한.

    Returns:
        {티커: 날짜 오름차순 Bar 리스트}.
    """
    out: dict[str, list[Bar]] = {}
    groups: list[Sequence[str] | None] = (
        [None] if tickers is None else list(chunked(list(tickers), chunk))
    )
    for group in groups:
        _fetch_daily_group(client, since, group, page, out)
    return out


def _fetch_daily_group(
    client: SupabaseLike,
    since: str,
    tickers: Sequence[str] | None,
    page: int,
    out: dict[str, list[Bar]],
) -> None:
    """티커 묶음 하나를 페이지네이션으로 읽어 `out`에 담는다."""
    offset = 0

    while True:
        query = (
            client.table(BARS_TABLE)
            .select("ticker,d,o,h,l,c,v,a")
            .eq("timeframe", TIMEFRAME_CODE["daily"])
            .gte("d", since)
        )
        if tickers is not None:
            query = query.in_("ticker", list(tickers))

        rows = query.order("ticker").order("d").range(offset, offset + page - 1).execute().data
        if not rows:
            break

        for r in rows:
            out.setdefault(str(r["ticker"]), []).append(
                Bar(
                    date=str(r["d"]),
                    open=int(r["o"]), high=int(r["h"]), low=int(r["l"]), close=int(r["c"]),
                    volume=int(r["v"]),
                    amount=None if r.get("a") is None else int(r["a"]),
                )
            )

        if len(rows) < page:
            break
        offset += page


def fetch_all_tickers(client: SupabaseLike, page: int = DEFAULT_PAGE) -> list[Ticker]:
    """`ksc_tickers` 전체를 티커 오름차순으로 읽는다.

    **Supabase REST는 응답을 1000행에서 조용히 자른다.** `select("*")`만 쓰면
    전 종목(약 2,763개) 중 1000개만 돌아오고, 오류도 나지 않는다 —
    실제로 전 종목 백필을 돌리다 `[50/1000]`을 보고서야 알았다.

    Args:
        client: Supabase 클라이언트.
        page: 페이지 크기.

    Returns:
        Ticker 리스트 (티커 오름차순).
    """
    out: list[Ticker] = []
    offset = 0

    while True:
        rows = (
            client.table(TICKERS_TABLE)
            .select("ticker,name,market,sector")
            .order("ticker")
            .range(offset, offset + page - 1)
            .execute()
            .data
        )
        if not rows:
            break

        out.extend(
            Ticker(
                ticker=str(r["ticker"]),
                name=str(r["name"]),
                market=str(r["market"]),
                sector=str(r.get("sector") or ""),
            )
            for r in rows
        )

        if len(rows) < page:
            break
        offset += len(rows)

    return out
