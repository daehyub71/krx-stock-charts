"""지수 시계열 수집 (하위 `krx-signal-verify` V12 요청, 2026-09-05).

「수집은 charts가, 판단은 하위가」 — 시총(F8)·수급(F14)·공매도와 같은 원칙이다.
하위는 판정의 **기준선**으로 쓴다: 종목 수익률에서 소속 시장 지수 수익률을 뺀 초과수익.

지키는 것:
  · **`1001`=코스피 · `2001`=코스닥** (2026-09-05 이름 조회로 확인).
    KIS는 코스피가 `0001`·코스닥이 `1001`이라 **`1001`이 두 체계에서 다른 시장**이다.
    `0001`은 pykrx에 아예 없다(0행) — 헷갈리면 코스닥 값을 코스피로 저장하게 된다
  · **KRX 로그인이 없으면 예외 없이 0행**이 온다 — R6와 같은 계열이라 0행을 실패로 가른다
  · 지수는 종목이 아니다 — `ksc_bars`는 `ksc_tickers` FK와 `^[0-9A-Z]{6}$`가 있어 섞을 수 없다
  · 시세 수집이 실패해도 지수 때문에 워크플로가 멈추지 않는다 (F8과 같은 원칙)
"""

from __future__ import annotations

import pathlib
import re
from datetime import date
from typing import Any

import pytest

from pipeline import krx_client, models, store, update

SQL = (pathlib.Path(__file__).resolve().parent.parent / "supabase" / "schema.sql").read_text(
    encoding="utf-8"
)


def table(name: str) -> str:
    return SQL.split(f"create table if not exists {name} (", 1)[1].split("\n);", 1)[0]


# ── 지수 코드 (이 파일에서 가장 중요한 것) ────────────────────────


def test_index_codes_are_the_pykrx_ones() -> None:
    """**`1001`이 두 체계에서 다른 시장이다.** pykrx 코스피 `1001` / KIS 코스피 `0001`."""
    assert krx_client.INDEXES == (("KOSPI", "1001"), ("KOSDAQ", "2001"))


def test_the_kis_code_is_never_used() -> None:
    """`0001`은 pykrx에 없다(0행 실측) — 적혀 있으면 누군가 KIS 문서를 보고 쓴 것이다."""
    src = pathlib.Path(krx_client.__file__).read_text(encoding="utf-8")
    assert '"0001"' not in src and "'0001'" not in src


def test_market_names_match_the_ticker_table() -> None:
    """`ksc_tickers.market`과 같은 말이어야 한다 — 하위가 그것으로 지수를 고른다."""
    assert {m for m, _ in krx_client.INDEXES} == set(krx_client.MARKETS)


# ── 파싱 ──────────────────────────────────────────────────────────


class FakeFrame:
    """pykrx DataFrame 대역 — `itertuples` 없이 최소만."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.empty = not rows

    def iterrows(self) -> Any:
        for d, o, h, low, c, v, a in self._rows:
            yield d, {"시가": o, "고가": h, "저가": low, "종가": c, "거래량": v, "거래대금": a}


def frame(*rows: tuple[Any, ...]) -> FakeFrame:
    return FakeFrame(list(rows))


def test_rows_become_index_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        krx_client, "_stock",
        lambda: type("S", (), {"get_index_ohlcv": staticmethod(
            lambda f, t, c, name_display=True: frame(
                (date(2026, 9, 3), 6500.1, 6600.2, 6480.0, 6579.48, 1234, 5678)
            )
        )})(),
    )
    got = krx_client.get_index_ohlcv("1001", "20260903", "20260903")
    assert len(got) == 1
    bar = got[0]
    assert bar.date == "2026-09-03"
    assert bar.close == pytest.approx(6579.48)
    assert bar.volume == 1234
    assert bar.amount == 5678


def test_an_empty_result_is_a_failure_not_a_holiday(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ **KRX 로그인이 없으면 예외 없이 0행**이 온다 (2026-09-05 실측).

    휴장일도 0행이라 겉보기가 같다 — 그래서 **부르는 쪽이 날짜로 가른다.**
    여기서는 빈 목록을 그대로 돌려주고, `update_index_bars`가 판단한다.
    """
    monkeypatch.setattr(
        krx_client, "_stock",
        lambda: type("S", (), {"get_index_ohlcv": staticmethod(
            lambda f, t, c, name_display=True: frame()
        )})(),
    )
    assert krx_client.get_index_ohlcv("1001", "20260903", "20260903") == []


def test_the_name_lookup_is_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """`name_display`가 켜져 있으면 지수명 조회에서 죽는다 — 값과 무관한 장식이다 (실측)."""
    seen: dict[str, Any] = {}

    def fake(f: str, t: str, c: str, name_display: bool = True) -> Any:
        seen["name_display"] = name_display
        return frame()

    monkeypatch.setattr(krx_client, "_stock",
                        lambda: type("S", (), {"get_index_ohlcv": staticmethod(fake)})())
    krx_client.get_index_ohlcv("1001", "20260903", "20260903")
    assert seen["name_display"] is False


# ── 스키마 ────────────────────────────────────────────────────────


def test_the_index_table_exists() -> None:
    assert "create table if not exists ksc_index_bars" in SQL


def test_indexes_are_not_mixed_into_the_ticker_bars() -> None:
    """`ksc_bars`는 `ksc_tickers` FK와 `^[0-9A-Z]{6}$`가 있어 지수를 넣을 수 없다."""
    body = table("ksc_index_bars")
    assert "references ksc_tickers" not in body
    assert "market" in body


def test_the_close_is_not_an_integer() -> None:
    """지수는 소수점이 있다 (6,579.48). 정수로 저장하면 0.5% 오차가 초과수익에 그대로 실린다."""
    body = table("ksc_index_bars")
    assert re.search(r"\bc\s+numeric", body), body


def test_the_key_is_market_and_day() -> None:
    assert "primary key (market, d)" in table("ksc_index_bars")


def test_only_the_two_markets_are_allowed() -> None:
    body = table("ksc_index_bars")
    assert "check (market in ('KOSPI', 'KOSDAQ'))" in body


def test_new_columns_use_add_column_if_not_exists() -> None:
    """`create table if not exists`는 마이그레이션이 아니다 — 기존 DB에 열을 늘릴 때."""
    assert "add column if not exists" in SQL


# ── 저장 ──────────────────────────────────────────────────────────


class FakeClient:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.tables: list[str] = []

    def table(self, name: str) -> FakeClient:
        self.tables.append(name)
        return self

    def upsert(self, rows: Any, on_conflict: str = "") -> FakeClient:
        self.rows.extend(rows if isinstance(rows, list) else [rows])
        self.conflict = on_conflict
        return self

    def execute(self) -> None:
        return None


def bars(n: int = 3) -> list[models.Bar]:
    return [
        models.Bar(date=f"2026-09-0{i + 1}", open=1.0, high=2.0, low=0.5,
                   close=1.5, volume=10, amount=20)
        for i in range(n)
    ]


def test_saving_keeps_the_market(monkeypatch: pytest.MonkeyPatch) -> None:
    c = FakeClient()
    n = store.upsert_index_bars(c, "KOSPI", bars(2))
    assert n == 2
    assert c.tables[0] == "ksc_index_bars"
    assert {r["market"] for r in c.rows} == {"KOSPI"}
    assert c.conflict == "market,d"


def test_saving_nothing_touches_nothing() -> None:
    c = FakeClient()
    assert store.upsert_index_bars(c, "KOSPI", []) == 0
    assert c.tables == []


# ── 일일 갱신 ─────────────────────────────────────────────────────


def test_a_trading_day_with_no_rows_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """0행이 로그인 실패인지 휴장인지 **부르는 쪽이 가른다** (R6와 같은 계열)."""
    monkeypatch.setattr(krx_client, "get_index_ohlcv", lambda code, f, t: [])
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: True)
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    assert update.update_index_bars(FakeClient(), "20260903") == 0
    assert any("0행" in p for p in printed)


def test_a_holiday_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: False)
    called: list[Any] = []
    monkeypatch.setattr(krx_client, "get_index_ohlcv",
                        lambda code, f, t: called.append(code) or [])
    assert update.update_index_bars(FakeClient(), "20260906") == 0
    assert called == []


def test_both_markets_are_collected(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fetch(code: str, f: str, t: str) -> Any:
        seen.append(code)
        return bars(1)

    monkeypatch.setattr(krx_client, "get_index_ohlcv", fetch)
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: True)
    n = update.update_index_bars(FakeClient(), "20260903")
    assert seen == ["1001", "2001"]
    assert n == 2


def test_one_market_failing_does_not_lose_the_other(monkeypatch: pytest.MonkeyPatch) -> None:
    """지수는 보조 정보다 (F8과 같은 원칙) — 워크플로를 멈추지 않는다."""
    def fetch(code: str, f: str, t: str) -> Any:
        if code == "1001":
            raise krx_client.KrxError("KOSPI 실패")
        return bars(1)

    monkeypatch.setattr(krx_client, "get_index_ohlcv", fetch)
    monkeypatch.setattr(krx_client, "is_trading_day", lambda d: True)
    assert update.update_index_bars(FakeClient(), "20260903") == 1


# ── ksc_meta.updated_at (하위 요청, 2026-09-05) ──────────────────


def test_meta_upsert_sets_updated_at() -> None:
    """⚠ **`default now()`는 INSERT에만 걸린다.** upsert의 UPDATE 경로는 아무도 안 건드려
    행이 처음 만들어진 시각에 멈춘다 — 열은 2026-08-15인데 자료는 2026-09-04까지 있었다.
    """
    c = FakeClient()
    store.set_meta(c, "update", {"updated": "2026-09-04"})
    assert c.rows and "updated_at" in c.rows[0], c.rows


def test_the_stamp_is_a_timestamp() -> None:
    c = FakeClient()
    store.set_meta(c, "update", {})
    stamp = c.rows[0]["updated_at"]
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", str(stamp)), stamp
