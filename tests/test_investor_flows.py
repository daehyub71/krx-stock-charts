"""투자자별 순매수 수집 (SPEC F14, v2.2).

하위 `krx-signal-briefing`이 "차트 신호가 근거를 갖는가"를 판정할 때 쓰는 세 갈래 증거 중 하나다.
여기서는 **모으고 저장하는 일**만 한다 — 해석은 하위 프로젝트가 한다.

pykrx는 투자자 이름을 하나씩만 받는다. 그래서 시장 2 × 투자자 5 = 하루 10회 호출로
전 종목을 모은 뒤 **종목당 한 행**으로 합친다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from pipeline import krx_client, store, update
from pipeline.models import InvestorFlow

# ── 대역 ─────────────────────────────────────────────────────────


def frame(rows: dict[str, int]) -> pd.DataFrame:
    """pykrx가 주는 모양 — 티커가 index, 순매수거래대금 열이 있다."""
    df = pd.DataFrame(
        {"종목명": ["x"] * len(rows), "순매수거래대금": list(rows.values())},
        index=list(rows),
    )
    df.index.name = "티커"
    return df


def fake_pykrx(
    monkeypatch: pytest.MonkeyPatch, by_investor: dict[str, dict[str, int]]
) -> list[tuple[str, str]]:
    """투자자 이름별로 다른 표를 돌려주는 대역. 호출 (시장, 투자자)를 기록한다."""
    seen: list[tuple[str, str]] = []

    class Stub:
        @staticmethod
        def get_market_net_purchases_of_equities_by_ticker(
            fromdate: str, todate: str, market: str, investor: str
        ) -> pd.DataFrame:
            seen.append((market, investor))
            return frame(by_investor.get(investor, {}))

    monkeypatch.setattr(krx_client, "_stock", lambda: Stub())
    monkeypatch.setattr(krx_client.config, "REQUEST_DELAY", 0)
    return seen


# ── 수집 (F14) ───────────────────────────────────────────────────


def test_collects_every_investor_and_merges_by_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """투자자별로 따로 받아 **종목당 한 행**으로 합친다."""
    seen = fake_pykrx(
        monkeypatch,
        {
            "기관합계": {"005930": 10},
            "외국인": {"005930": -20, "000660": 7},
            "기타외국인": {"005930": -1},
            "개인": {"005930": 11},
            "기타법인": {"005930": 0},
        },
    )
    flows = krx_client.get_investor_flows("20260827", "KOSDAQ")
    assert flows["005930"] == InvestorFlow(
        inst_net=10, foreign_net=-20, foreign_etc_net=-1, indiv_net=11, corp_etc_net=0
    )
    # 한 투자자에게만 나온 종목도 남는다. 없는 값은 None이지 0이 아니다.
    assert flows["000660"] == InvestorFlow(
        inst_net=None, foreign_net=7, foreign_etc_net=None, indiv_net=None, corp_etc_net=None
    )
    assert [inv for _, inv in seen] == list(krx_client.INVESTORS)


def test_asks_for_one_day_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """하루치 시계열이 필요하다 — 기간 합계를 받으면 공시 당일 수급을 볼 수 없다."""
    args: list[tuple[str, str]] = []

    class Stub:
        @staticmethod
        def get_market_net_purchases_of_equities_by_ticker(
            fromdate: str, todate: str, market: str, investor: str
        ) -> pd.DataFrame:
            args.append((fromdate, todate))
            return frame({})

    monkeypatch.setattr(krx_client, "_stock", lambda: Stub())
    monkeypatch.setattr(krx_client.config, "REQUEST_DELAY", 0)
    krx_client.get_investor_flows("20260827", "KOSPI")
    assert set(args) == {("20260827", "20260827")}


def test_empty_response_is_a_holiday_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pykrx(monkeypatch, {})
    assert krx_client.get_investor_flows("20260815", "KOSPI") == {}


def test_a_missing_value_column_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """열 이름이 바뀌면 조용히 빈 값을 저장하지 말고 멈춘다."""

    class Stub:
        @staticmethod
        def get_market_net_purchases_of_equities_by_ticker(*a: Any, **k: Any) -> pd.DataFrame:
            df = pd.DataFrame({"종목명": ["x"]}, index=["005930"])
            df.index.name = "티커"
            return df

    monkeypatch.setattr(krx_client, "_stock", lambda: Stub())
    monkeypatch.setattr(krx_client.config, "REQUEST_DELAY", 0)
    with pytest.raises(krx_client.KrxError):
        krx_client.get_investor_flows("20260827", "KOSPI")


# ── 저장 ─────────────────────────────────────────────────────────

FLOW = InvestorFlow(inst_net=10, foreign_net=-20, foreign_etc_net=-1, indiv_net=11, corp_etc_net=0)


def test_rows_carry_the_date_and_every_column() -> None:
    (row,) = store.investor_flow_rows({"005930": FLOW}, date(2026, 8, 27))
    assert row == {
        "d": "2026-08-27",
        "ticker": "005930",
        "inst_net": 10,
        "foreign_net": -20,
        "foreign_etc_net": -1,
        "indiv_net": 11,
        "corp_etc_net": 0,
    }


def test_rows_keep_nulls_distinct_from_zero() -> None:
    """값이 없는 것과 0원은 다르다 — 0으로 채우면 '거래가 없었다'가 '안 받았다'를 덮는다."""
    (row,) = store.investor_flow_rows(
        {"005930": InvestorFlow(inst_net=None, foreign_net=0, foreign_etc_net=None,
                                indiv_net=None, corp_etc_net=None)},
        date(2026, 8, 27),
    )
    assert row["inst_net"] is None and row["foreign_net"] == 0


def test_rows_are_sorted_by_ticker() -> None:
    rows = store.investor_flow_rows({"9": FLOW, "1": FLOW, "5": FLOW}, date(2026, 8, 27))
    assert [r["ticker"] for r in rows] == ["1", "5", "9"]


class FakeTable:
    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []
        self.deleted: list[str] = []

    def upsert(self, rows: list[dict[str, Any]], on_conflict: str = "") -> FakeTable:
        self.batches.append(rows)
        self.conflict = on_conflict
        return self

    def delete(self) -> FakeTable:
        return self

    def lt(self, column: str, value: str) -> FakeTable:
        self.deleted.append(f"{column}<{value}")
        return self

    def execute(self) -> None:
        return None


class FakeClient:
    def __init__(self) -> None:
        self.t = FakeTable()

    def table(self, name: str) -> FakeTable:
        self.name = name
        return self.t


def test_upsert_writes_in_batches_keyed_by_day_and_ticker() -> None:
    c = FakeClient()
    flows = {f"{i:06d}": FLOW for i in range(5)}
    n = store.upsert_investor_flows(c, flows, date(2026, 8, 27), batch_size=2)
    assert n == 5
    assert [len(b) for b in c.t.batches] == [2, 2, 1]
    assert c.t.conflict == "d,ticker"
    assert c.name == store.INVESTOR_FLOWS_TABLE


def test_prune_deletes_rows_older_than_the_retention_window() -> None:
    """보존 기간을 안 두면 1년에 100만 행이 쌓인다."""
    c = FakeClient()
    store.prune_investor_flows(c, date(2026, 8, 27), keep_days=120)
    assert c.t.deleted == ["d<2026-04-29"]


# ── 갱신 (보조 정보다) ───────────────────────────────────────────


def test_update_collects_both_markets(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        update.krx_client, "get_investor_flows",
        lambda day, market: (seen.append(market), {"005930": FLOW})[1],
    )
    monkeypatch.setattr(update.store, "upsert_investor_flows", lambda *a, **k: 1)
    monkeypatch.setattr(update.store, "prune_investor_flows", lambda *a, **k: None)
    assert update.update_investor_flows(object(), "20260827") == 1
    assert seen == list(krx_client.MARKETS)


def test_update_swallows_a_krx_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """보조 정보다 — 수급이 하루 비는 것이 워크플로 실패보다 낫다 (F8과 같은 원칙)."""

    def boom(day: str, market: str) -> dict[str, InvestorFlow]:
        raise krx_client.KrxError("KRX 응답 없음")

    monkeypatch.setattr(update.krx_client, "get_investor_flows", boom)
    assert update.update_investor_flows(object(), "20260827") == 0


def test_update_does_nothing_on_a_holiday(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update.krx_client, "get_investor_flows", lambda day, market: {})
    called: list[str] = []
    monkeypatch.setattr(update.store, "upsert_investor_flows",
                        lambda *a, **k: called.append("upsert"))
    assert update.update_investor_flows(object(), "20260815") == 0
    assert called == []
