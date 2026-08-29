"""update 모듈 테스트 — 증분 갱신의 순수 로직 (SPEC F3)."""

from __future__ import annotations

from typing import Any

import pytest

from pipeline.models import Bar
from pipeline.update import detect_drift, month_start, tail_window_start


def bar(date: str, close: int = 100) -> Bar:
    return Bar(date=date, open=100, high=110, low=90, close=close, volume=10)


class TestMonthStart:
    @pytest.mark.parametrize(
        ("day", "expected"),
        [("2026-08-14", "2026-08-01"), ("2026-08-01", "2026-08-01"), ("2026-12-31", "2026-12-01")],
    )
    def test_first_of_month(self, day: str, expected: str) -> None:
        assert month_start(day) == expected


class TestTailWindowStart:
    def test_uses_month_start_when_earlier(self) -> None:
        """8/14(금)은 그 주 월요일이 8/10, 달 1일이 8/1 → 8/1이 이르다."""
        assert tail_window_start("2026-08-14") == "2026-08-01"

    def test_uses_monday_when_earlier(self) -> None:
        """9/1(화)은 그 주 월요일이 8/31로 달 1일(9/1)보다 이르다 — 주가 달을 넘는 경우."""
        assert tail_window_start("2026-09-01") == "2026-08-31"

    def test_covers_both_week_and_month(self) -> None:
        """어떤 날이든 그 주 월요일과 그 달 1일을 모두 포함해야 한다."""
        for day in ["2026-08-01", "2026-08-14", "2026-09-01", "2026-03-02", "2027-01-04"]:
            start = tail_window_start(day)
            from datetime import date, timedelta

            d = date.fromisoformat(day)
            monday = (d - timedelta(days=d.weekday())).isoformat()
            first = d.replace(day=1).isoformat()
            assert start <= monday and start <= first


class TestDetectDrift:
    """수정주가 소급 변경 감지 — 액면분할 시 과거 값까지 바뀐다."""

    def test_no_drift_when_closes_match(self) -> None:
        stored = [bar("2026-08-13", 100), bar("2026-08-14", 105)]
        fresh = [bar("2026-08-13", 100), bar("2026-08-14", 105)]
        assert detect_drift(stored, fresh) is False

    def test_drift_when_past_close_changed(self) -> None:
        """저장분 100원이 새로 받으니 50원 — 액면분할 신호."""
        stored = [bar("2026-08-13", 100), bar("2026-08-14", 105)]
        fresh = [bar("2026-08-13", 50), bar("2026-08-14", 52)]
        assert detect_drift(stored, fresh) is True

    def test_ignores_dates_absent_from_fresh(self) -> None:
        """새 조회에 없는 날짜는 판단 근거가 없으므로 무시한다."""
        stored = [bar("2026-08-01", 100), bar("2026-08-14", 105)]
        fresh = [bar("2026-08-14", 105)]
        assert detect_drift(stored, fresh) is False

    def test_single_changed_bar_is_enough(self) -> None:
        stored = [bar("2026-08-12", 100), bar("2026-08-13", 100), bar("2026-08-14", 100)]
        fresh = [bar("2026-08-12", 100), bar("2026-08-13", 99), bar("2026-08-14", 100)]
        assert detect_drift(stored, fresh) is True

    def test_empty_inputs_are_safe(self) -> None:
        assert detect_drift([], []) is False
        assert detect_drift([bar("2026-08-14")], []) is False


# ── F8 시가총액 갱신 — 봉 갱신과 분리된 보조 단계 (v2.1) ──────────

from datetime import date as _date  # noqa: E402

from pipeline import krx_client as _krx  # noqa: E402
from pipeline import store as _store  # noqa: E402
from pipeline import update as _update  # noqa: E402
from pipeline.models import MarketCap, Ticker  # noqa: E402

_CAPS = {"005930": MarketCap(mktcap=100, list_shrs=10), "000660": MarketCap(mktcap=50, list_shrs=5)}


_METAS = [
    Ticker(ticker="005930", name="삼성전자", market="KOSPI", sector=""),
    Ticker(ticker="999999", name="시총없음", market="KOSPI", sector=""),
]


def test_update_market_caps_saves_known_tickers(monkeypatch: Any) -> None:
    """pykrx는 전 종목을 주지만 ksc_tickers에 있는 종목만 저장된다 (market_cap_rows가 거른다)."""
    saved: dict[str, Any] = {}
    monkeypatch.setattr(_krx, "get_market_caps", lambda d: _CAPS)

    def fake_upsert(c: Any, tickers: Any, caps: dict[str, MarketCap], d: Any) -> int:
        saved.update({"tickers": tickers, "caps": caps, "d": d})
        return sum(1 for t in tickers if t.ticker in caps)

    monkeypatch.setattr(_store, "upsert_market_caps", fake_upsert)
    n = _update.update_market_caps(object(), "20260827", _METAS)
    assert n == 1 and saved["d"] == _date(2026, 8, 27) and saved["tickers"] == _METAS


def test_update_market_caps_returns_zero_when_krx_fails(monkeypatch: Any) -> None:
    """시총은 보조 정보다 — 실패해도 예외를 올리지 않는다 (봉 갱신은 이미 끝났다)."""

    def boom(d: str) -> dict[str, MarketCap]:
        raise _krx.KrxError("시총 조회 실패")

    monkeypatch.setattr(_krx, "get_market_caps", boom)
    assert _update.update_market_caps(object(), "20260827", _METAS) == 0


def test_update_market_caps_empty_result_is_zero(monkeypatch: Any) -> None:
    monkeypatch.setattr(_krx, "get_market_caps", lambda d: {})
    assert _update.update_market_caps(object(), "20260827", _METAS) == 0
