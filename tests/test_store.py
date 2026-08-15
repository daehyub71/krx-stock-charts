"""store 모듈 테스트 — Supabase 클라이언트를 가짜로 대체해 순수 로직만 검증한다."""

from __future__ import annotations

from typing import Any

from pipeline.models import Ticker
from pipeline.store import TICKERS_TABLE, chunked, ticker_rows, upsert_tickers


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
