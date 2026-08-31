"""store 모듈 테스트 — Supabase 클라이언트를 가짜로 대체해 순수 로직만 검증한다."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from pipeline import store
from pipeline.models import Bar, Ticker
from pipeline.store import (
    TICKERS_TABLE,
    chunked,
    fetch_all_tickers,
    ticker_rows,
    upsert_tickers,
)


class FakeQuery:
    """supabase-py의 체이닝 쿼리를 흉내 내는 스텁."""

    def __init__(self, recorder: list[dict[str, Any]], table: str) -> None:
        self._rec = recorder
        self._table = table
        self._payload: list[dict[str, Any]] | None = None

    def upsert(self, rows: list[dict[str, Any]], **kwargs: Any) -> FakeQuery:
        self._payload = rows
        self._rec.append({"table": self._table, "rows": rows, "kwargs": kwargs})
        return self

    def execute(self) -> object:
        return object()


class PagedRange:
    """Supabase가 1000행에서 잘라 돌려주는 동작을 흉내 낸다."""

    CAP = 1000

    def __init__(self, total: int, ranges: list[tuple[int, int]]) -> None:
        self._total, self._ranges = total, ranges

    def select(self, *_a: Any, **_k: Any) -> PagedRange:
        return self

    def order(self, *_a: Any, **_k: Any) -> PagedRange:
        return self

    def range(self, start: int, end: int) -> PagedRange:
        self._ranges.append((start, end))
        self._start, self._end = start, end
        return self

    def execute(self) -> Any:
        size = min(self._end - self._start + 1, self.CAP)
        n = max(0, min(size, self._total - self._start))
        rows = [
            {
                "ticker": f"{self._start + i:06d}",
                "name": f"종목{i}",
                "market": "KOSPI",
                "sector": "",
            }
            for i in range(n)
        ]
        return type("R", (), {"data": rows})()


class PagedClient:
    def __init__(self, total: int) -> None:
        self.total, self.ranges = total, []

    def table(self, _name: str) -> PagedRange:
        return PagedRange(self.total, self.ranges)


class FakeClient:
    """호출 내역만 기록하는 가짜 Supabase 클라이언트."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self.calls, name)


class TestChunked:
    """대량 upsert를 나누는 유틸."""

    def test_splits_into_even_chunks(self) -> None:
        assert list(chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]

    def test_last_chunk_may_be_short(self) -> None:
        assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_empty_yields_nothing(self) -> None:
        assert list(chunked([], 3)) == []

    def test_size_larger_than_input(self) -> None:
        assert list(chunked([1, 2], 10)) == [[1, 2]]


class TestTickerRows:
    """Ticker → Supabase 행 변환."""

    def test_maps_all_columns(self) -> None:
        rows = ticker_rows([Ticker("005930", "삼성전자", "KOSPI", "전기·전자")])
        assert rows == [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "전기·전자"}
        ]

    def test_preserves_alphanumeric_ticker(self) -> None:
        """0126Z0 같은 문자 포함 티커가 손상되지 않아야 한다."""
        rows = ticker_rows([Ticker("0126Z0", "삼성에피스홀딩스", "KOSPI", "기타금융")])
        assert rows[0]["ticker"] == "0126Z0"

    def test_empty_input(self) -> None:
        assert ticker_rows([]) == []


class TestUpsertTickers:
    """멱등 저장 — upsert이므로 같은 데이터를 두 번 써도 중복되지 않는다."""

    def test_sends_rows_to_correct_table(self) -> None:
        client = FakeClient()
        upsert_tickers(client, [Ticker("005930", "삼성전자", "KOSPI", "전기·전자")])

        assert len(client.calls) == 1
        assert client.calls[0]["table"] == TICKERS_TABLE
        assert client.calls[0]["rows"][0]["ticker"] == "005930"

    def test_uses_ticker_as_conflict_key(self) -> None:
        """on_conflict가 없으면 재실행 시 PK 충돌로 실패한다."""
        client = FakeClient()
        upsert_tickers(client, [Ticker("005930", "삼성전자", "KOSPI", "")])
        assert client.calls[0]["kwargs"].get("on_conflict") == "ticker"

    def test_splits_large_batches(self) -> None:
        client = FakeClient()
        tickers = [Ticker(f"{i:06d}", f"종목{i}", "KOSPI", "") for i in range(250)]
        upsert_tickers(client, tickers, batch_size=100)

        assert len(client.calls) == 3
        assert [len(c["rows"]) for c in client.calls] == [100, 100, 50]

    def test_no_call_for_empty_input(self) -> None:
        client = FakeClient()
        upsert_tickers(client, [])
        assert client.calls == []

    def test_returns_written_count(self) -> None:
        client = FakeClient()
        n = upsert_tickers(client, [Ticker("005930", "삼성전자", "KOSPI", "")])
        assert n == 1


class TestFetchAllTickers:
    """1000행 상한 대응 — 전 종목(2,763개)은 한 페이지에 안 들어간다."""

    def test_pages_past_the_thousand_row_cap(self) -> None:
        client = PagedClient(total=2763)
        rows = fetch_all_tickers(client)
        assert len(rows) == 2763
        assert len(client.ranges) > 1

    def test_single_request_when_under_one_page(self) -> None:
        client = PagedClient(total=300)
        assert len(fetch_all_tickers(client)) == 300
        assert len(client.ranges) == 1

    def test_requests_contiguous_ranges(self) -> None:
        client = PagedClient(total=2763)
        fetch_all_tickers(client)
        for i in range(1, len(client.ranges)):
            assert client.ranges[i][0] == client.ranges[i - 1][1] + 1

    def test_empty_table(self) -> None:
        client = PagedClient(total=0)
        assert fetch_all_tickers(client) == []

    def test_returns_ticker_objects(self) -> None:
        client = PagedClient(total=2)
        out = fetch_all_tickers(client)
        assert out[0].ticker == "000000" and out[0].market in ("KOSPI", "KOSDAQ")


# ── F8 시가총액·상장주식수 (v2.1) ─────────────────────────────────

from datetime import date  # noqa: E402

from pipeline.models import MarketCap  # noqa: E402
from pipeline.store import market_cap_rows, upsert_market_caps  # noqa: E402

CAPS = {
    "005930": MarketCap(mktcap=1_555_110_109_728_000, list_shrs=5_846_278_608),
    "079940": MarketCap(mktcap=611_312_156_200, list_shrs=13_420_684),
}



TICKER_METAS = [
    Ticker(ticker="005930", name="삼성전자", market="KOSPI", sector="전기전자"),
    Ticker(ticker="079940", name="가비아", market="KOSDAQ", sector="서비스"),
    Ticker(ticker="999999", name="시총없음", market="KOSPI", sector=""),
]


def test_market_cap_rows_carry_meta_and_basis_date() -> None:
    """PostgREST upsert는 행 전체를 다시 쓴다 — 메타를 빼면 name이 null이 된다 (2026-08-29 실측)."""
    rows = market_cap_rows(TICKER_METAS, CAPS, date(2026, 8, 27))
    assert rows[0] == {
        "ticker": "005930",
        "name": "삼성전자",
        "market": "KOSPI",
        "sector": "전기전자",
        "mktcap": 1_555_110_109_728_000,
        "list_shrs": 5_846_278_608,
        "mktcap_d": "2026-08-27",
    }
    assert [r["ticker"] for r in rows] == ["005930", "079940"]  # 시총 없는 종목은 빠진다


def test_market_cap_rows_empty_safe() -> None:
    assert market_cap_rows(TICKER_METAS, {}, date(2026, 8, 27)) == []
    assert market_cap_rows([], CAPS, date(2026, 8, 27)) == []


def test_upsert_market_caps_sends_full_rows() -> None:
    client = FakeClient()
    assert upsert_market_caps(client, TICKER_METAS, CAPS, date(2026, 8, 27)) == 2
    assert client.calls[0]["table"] == TICKERS_TABLE
    assert client.calls[0]["kwargs"].get("on_conflict") == "ticker"
    assert set(client.calls[0]["rows"][0]) == {
        "ticker",
        "name",
        "market",
        "sector",
        "mktcap",
        "list_shrs",
        "mktcap_d",
    }


def test_upsert_market_caps_noop_when_empty() -> None:
    client = FakeClient()
    assert upsert_market_caps(client, TICKER_METAS, {}, date(2026, 8, 27)) == 0
    assert client.calls == []


# ── 티커 필터는 나눠 보낸다 (2026-08-30 실장애) ──────────────────
#
# `.in_()`은 쿼리 문자열에 들어간다. 2,700개를 한 번에 넣으면 URL이 길어져 PostgREST가
# `400 Bad Request`를 돌려준다 — 응답 본문이 JSON이 아니어서 supabase-py는
# "JSON could not be generated"로 다시 감싼다. 이 실패가 08-18부터 상위 워크플로를
# 매일 빨간불로 만들었고, 주·월봉 재계산과 08/28 일봉이 그대로 빠졌다.


class RecordingTable:
    """`.in_()`에 몇 개씩 들어오는지 기록하는 대역."""

    def __init__(self, rows_by_call: list[list[dict[str, Any]]]) -> None:
        self.rows_by_call = rows_by_call
        self.in_sizes: list[int] = []
        self._call = 0

    def select(self, *a: Any, **k: Any) -> RecordingTable:
        return self

    def eq(self, *a: Any, **k: Any) -> RecordingTable:
        return self

    def gte(self, *a: Any, **k: Any) -> RecordingTable:
        return self

    def in_(self, column: str, values: list[str]) -> RecordingTable:
        self.in_sizes.append(len(values))
        return self

    def order(self, *a: Any, **k: Any) -> RecordingTable:
        return self

    def range(self, *a: Any, **k: Any) -> RecordingTable:
        return self

    def execute(self) -> Any:
        rows = self.rows_by_call[self._call] if self._call < len(self.rows_by_call) else []
        self._call += 1
        return SimpleNamespace(data=rows)


class RecordingClient:
    def __init__(self, table: RecordingTable) -> None:
        self._table = table

    def table(self, name: str) -> RecordingTable:
        return self._table


def test_fetch_daily_since_splits_a_long_ticker_filter() -> None:
    """2,700개를 한 번에 보내면 URL이 길어 400이 난다 — 나눠 보낸다."""
    t = RecordingTable([[]] * 40)
    tickers = [f"{i:06d}" for i in range(2700)]
    store.fetch_daily_since(RecordingClient(t), "2026-08-01", tickers=tickers)
    assert t.in_sizes, "티커 필터가 전달되지 않았다"
    assert max(t.in_sizes) <= store.TICKER_FILTER_CHUNK
    assert sum(t.in_sizes) == len(tickers)


def test_fetch_daily_since_merges_chunks_into_one_result() -> None:
    """나눠 보내도 종목별 결과는 하나로 합쳐진다."""
    bar = {"ticker": "000001", "d": "2026-08-03", "o": 1, "h": 2, "l": 1, "c": 2, "v": 3, "a": 4}
    other = {**bar, "ticker": "000002"}
    # 묶음당 한 번씩 — 각 응답이 page보다 짧으면 그 묶음은 거기서 끝난다.
    t = RecordingTable([[bar], [other]])
    out = store.fetch_daily_since(
        RecordingClient(t), "2026-08-01", tickers=["000001", "000002"], chunk=1
    )
    assert sorted(out) == ["000001", "000002"]


def test_fetch_daily_since_without_a_ticker_filter_still_works() -> None:
    t = RecordingTable([[]])
    store.fetch_daily_since(RecordingClient(t), "2026-08-01")
    assert t.in_sizes == []


# ── 종목을 가로질러 묶어 쓴다 (2026-08-30) ───────────────────────
#
# `upsert_bars`는 한 종목 안에서만 묶는다. 일일 갱신은 종목당 봉이 1개라 요청이
# **종목 수만큼** 나간다 — 2,700회. 주·월봉까지 더하면 8,000회가 되고,
# 워크플로 제한이 30분인데 40~50분이 걸린다. 거래일 실행이 매번 잘린 진짜 이유다.


def a_bar(d: str = "2026-08-27") -> Bar:
    return Bar(date=d, open=1, high=2, low=1, close=2, volume=3, amount=4)


def test_upsert_bars_bulk_packs_many_tickers_into_one_request() -> None:
    c = FakeClient()
    items = {f"{i:06d}": [a_bar()] for i in range(2500)}
    n = store.upsert_bars_bulk(c, "daily", items, batch_size=1000)
    assert n == 2500
    assert [len(call["rows"]) for call in c.calls] == [1000, 1000, 500]  # 2,500회 → 3회


def test_upsert_bars_bulk_keeps_the_conflict_target() -> None:
    c = FakeClient()
    store.upsert_bars_bulk(c, "daily", {"005930": [a_bar()]})
    assert c.calls[0]["table"] == store.BARS_TABLE
    assert c.calls[0]["kwargs"]["on_conflict"] == "ticker,timeframe,d"


def test_upsert_bars_bulk_writes_each_tickers_rows() -> None:
    c = FakeClient()
    store.upsert_bars_bulk(
        c, "weekly", {"005930": [a_bar()], "000660": [a_bar(), a_bar("2026-08-20")]}
    )
    written = [r for call in c.calls for r in call["rows"]]
    assert len(written) == 3
    assert {r["ticker"] for r in written} == {"005930", "000660"}


def test_upsert_bars_bulk_with_nothing_makes_no_request() -> None:
    c = FakeClient()
    assert store.upsert_bars_bulk(c, "daily", {}) == 0
    assert c.calls == []
