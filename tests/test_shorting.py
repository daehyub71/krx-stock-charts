"""공매도 거래량·비중 수집 (SPEC F15 — 하위 `krx-signal-verify` V6b 요청, 2026-09-07).

「수집은 charts가, 판단은 하위가」 — 시총(F8)·수급(F14)·지수와 같은 원칙이다.
하위는 종목 화면에 20거래일 추이를 붙이고, 없으면 그 갈래를 「생략」으로 표기한다 (없어도 되는 층).

지키는 것:
  · `get_shorting_volume_by_ticker(date, market)`는 **시장당 1회로 전 종목**을 준다
    (2026-09-07 실측: KOSPI 943행 · KOSDAQ 1,822행, 열 `공매도·매수·비중`)
  · ⚠ **휴장일을 물으면 예외 없이 직전 거래일 자료가 그대로 온다** (일요일 → 943행, 실측).
    날짜를 달아 저장하면 금요일 값이 일요일로 남는다 — `is_trading_day`를 **먼저** 본다
  · 공매도 0주는 실제 값이다(943행 중 119행) — 0을 null로 바꾸지 않는다
  · 티커는 숫자가 아니다 — `00104K`·`0099X0`이 실재한다
  · 보조 정보다 — 실패해도 워크플로를 멈추지 않는다 (F8과 같은 원칙)
"""

from __future__ import annotations

import pathlib
from datetime import date
from typing import Any

import pytest

from pipeline import krx_client, models, store, update

SQL = (pathlib.Path(__file__).resolve().parent.parent / "supabase" / "schema.sql").read_text(
    encoding="utf-8"
)


def table(name: str) -> str:
    return SQL.split(f"create table if not exists {name} (", 1)[1].split("\n);", 1)[0]


# ── 파싱 ──────────────────────────────────────────────────────────


class FakeFrame:
    """pykrx DataFrame 대역 — 인덱스가 티커, 열이 공매도·매수·비중."""

    def __init__(
        self, rows: dict[str, tuple[int, int, float]],
        cols: tuple[str, ...] = ("공매도", "매수", "비중"),
    ) -> None:
        self._rows = rows
        self.columns = list(cols)
        self.empty = not rows

    def iterrows(self) -> Any:
        for t, (s, b, r) in self._rows.items():
            yield t, dict(zip(self.columns, (s, b, r), strict=False))


def stock_with(frame: FakeFrame) -> Any:
    return type("S", (), {"get_shorting_volume_by_ticker": staticmethod(lambda d, m: frame)})()


def test_rows_become_short_volumes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(krx_client, "_stock", lambda: stock_with(FakeFrame({
        "095570": (1819, 57218, 3.18), "00104K": (0, 1200, 0.0),
    })))
    monkeypatch.setattr(krx_client.time, "sleep", lambda s: None)
    got = krx_client.get_shorting_volumes("20260904", "KOSPI")
    assert got["095570"] == models.ShortVolume(short_vol=1819, buy_vol=57218, ratio=3.18)
    assert got["00104K"].short_vol == 0, "0주는 실제 값이다 — null이 아니다"


def test_an_empty_frame_is_empty_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(krx_client, "_stock", lambda: stock_with(FakeFrame({})))
    monkeypatch.setattr(krx_client.time, "sleep", lambda s: None)
    assert krx_client.get_shorting_volumes("20260904", "KOSPI") == {}


def test_missing_columns_are_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """KRX 응답 열이 바뀌면 조용히 0을 저장하지 않는다 — 잔고 함수가 그렇게 깨졌다 (하위 R6)."""
    monkeypatch.setattr(krx_client, "_stock", lambda: stock_with(
        FakeFrame({"095570": (1, 2, 3.0)}, cols=("SHORT", "BUY", "RATIO"))
    ))
    monkeypatch.setattr(krx_client.time, "sleep", lambda s: None)
    with pytest.raises(krx_client.KrxError, match="열"):
        krx_client.get_shorting_volumes("20260904", "KOSPI")


def test_the_client_warns_about_the_holiday_remap() -> None:
    """함수 자체는 휴장일을 못 가른다 — 부르는 쪽이 `is_trading_day`를 먼저 본다고 적혀 있다."""
    assert "is_trading_day" in (krx_client.get_shorting_volumes.__doc__ or "")


# ── 스키마 ────────────────────────────────────────────────────────


def test_the_table_exists_with_the_agreed_columns() -> None:
    """하위 `krx-signal-verify/shorting.py`가 이 이름으로 읽는다 — 바꾸면 그쪽도 바꾼다."""
    block = table("ksc_shorting")
    for col in ("d ", "ticker ", "short_vol ", "buy_vol ", "ratio "):
        assert col in block, col


def test_the_key_is_day_and_ticker() -> None:
    assert "primary key (d, ticker)" in table("ksc_shorting")


def test_read_shape_index_exists() -> None:
    """하위는 「종목 N개 × 최근 20거래일」로 읽는다 — 수급과 같은 모양의 인덱스."""
    assert "ksc_shorting (ticker, d desc)" in SQL


def test_rls_is_on_with_a_read_policy() -> None:
    assert "alter table ksc_shorting enable row level security" in SQL
    assert ("create policy ksc_shorting_read on ksc_shorting "
            "for select to anon, authenticated") in SQL


# ── 행 · 저장 · 정리 ──────────────────────────────────────────────


class FakeClient:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.tables: list[str] = []
        self.deleted_before: str | None = None

    def table(self, name: str) -> FakeClient:
        self.tables.append(name)
        return self

    def upsert(self, rows: Any, on_conflict: str = "") -> FakeClient:
        self.rows.extend(rows if isinstance(rows, list) else [rows])
        self.conflict = on_conflict
        return self

    def delete(self) -> FakeClient:
        return self

    def lt(self, col: str, value: str) -> FakeClient:
        self.deleted_before = value
        return self

    def execute(self) -> None:
        return None


VOLS = {"095570": models.ShortVolume(1819, 57218, 3.18), "00104K": models.ShortVolume(0, 1200, 0.0)}


def test_rows_carry_the_date_and_every_column() -> None:
    rows = store.short_volume_rows(VOLS, date(2026, 9, 4))
    assert rows[0] == {"d": "2026-09-04", "ticker": "00104K", "short_vol": 0, "buy_vol": 1200,
                       "ratio": 0.0}
    assert [r["ticker"] for r in rows] == ["00104K", "095570"], "티커 오름차순"


def test_upsert_is_keyed_by_day_and_ticker() -> None:
    c = FakeClient()
    assert store.upsert_shorting(c, VOLS, date(2026, 9, 4)) == 2
    assert c.tables[0] == "ksc_shorting" and c.conflict == "d,ticker"


def test_prune_uses_the_shared_retention() -> None:
    c = FakeClient()
    store.prune_shorting(c, date(2026, 9, 4))
    from datetime import timedelta

    cutoff = date(2026, 9, 4) - timedelta(days=store.RETENTION_DAYS)
    assert c.deleted_before == cutoff.isoformat()


# ── 일일 갱신 ─────────────────────────────────────────────────────


def test_a_holiday_never_calls_krx(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ 휴장일에 물으면 직전 거래일 자료가 그대로 온다 — 부르지도 않아야 한다."""
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: False)
    called: list[str] = []
    monkeypatch.setattr(krx_client, "get_shorting_volumes", lambda d, m: called.append(m) or VOLS)
    assert update.update_shorting(FakeClient(), "20260906") == 0
    assert called == []


def test_both_markets_are_collected_and_pruned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: True)
    seen: list[str] = []

    def fetch(d: str, m: str) -> Any:
        seen.append(m)
        return {{"KOSPI": "A00001", "KOSDAQ": "B00001"}[m]: models.ShortVolume(1, 2, 50.0)}

    monkeypatch.setattr(krx_client, "get_shorting_volumes", fetch)
    c = FakeClient()
    assert update.update_shorting(c, "20260904") == 2
    assert seen == ["KOSPI", "KOSDAQ"]
    assert c.deleted_before is not None, "보존 기간 정리를 빼먹었다"


def test_a_trading_day_with_no_rows_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """거래일인데 0행이면 로그인 실패다 — 조용히 넘기면 「정상적으로 비어 있는」 상태로 지나간다."""
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: True)
    monkeypatch.setattr(krx_client, "get_shorting_volumes", lambda d, m: {})
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    assert update.update_shorting(FakeClient(), "20260904") == 0
    assert any("0행" in p for p in printed)


def test_one_market_failing_does_not_lose_the_other(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: True)

    def fetch(d: str, m: str) -> Any:
        if m == "KOSPI":
            raise krx_client.KrxError("KOSPI 실패")
        return VOLS

    monkeypatch.setattr(krx_client, "get_shorting_volumes", fetch)
    assert update.update_shorting(FakeClient(), "20260904") == 2
