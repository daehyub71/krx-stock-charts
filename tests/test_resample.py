"""resample 모듈 테스트 — 일봉 → 주봉/월봉 (SPEC F4).

경계 케이스를 두껍게 둔다. 리샘플 구현이 Python 한 벌뿐이므로(D4),
여기가 틀리면 화면에서 걸러낼 방법이 없다.
"""

from __future__ import annotations

import pytest

from pipeline.models import Bar
from pipeline.resample import resample, week_start


def bar(date: str, o: int, h: int, low: int, c: int, v: int, a: int | None = None) -> Bar:
    """테스트용 Bar 생성 헬퍼."""
    return Bar(date=date, open=o, high=h, low=low, close=c, volume=v, amount=a)


class TestWeekStart:
    """주 경계는 월요일 시작(ISO 주)."""

    @pytest.mark.parametrize(
        ("date", "expected"),
        [
            ("2026-08-10", "2026-08-10"),  # 월요일 → 자기 자신
            ("2026-08-11", "2026-08-10"),  # 화요일
            ("2026-08-14", "2026-08-10"),  # 금요일
            ("2026-08-16", "2026-08-10"),  # 일요일 → 같은 주
            ("2026-08-17", "2026-08-17"),  # 다음 월요일
        ],
    )
    def test_monday_is_week_start(self, date: str, expected: str) -> None:
        assert week_start(date) == expected

    def test_crosses_month_boundary(self) -> None:
        """월이 바뀌어도 주는 월요일 기준으로 이어진다."""
        assert week_start("2026-09-01") == week_start("2026-08-31")


class TestResampleDaily:
    """일봉은 파생이 없다."""

    def test_returns_input_unchanged(self) -> None:
        bars = [bar("2026-08-10", 100, 110, 95, 105, 10)]
        assert resample(bars, "daily") == bars

    def test_empty_input(self) -> None:
        assert resample([], "daily") == []


class TestResampleWeekly:
    """주봉 묶기 규칙 — 시가=첫, 종가=끝, 고저=최대최소, 거래량=합."""

    def test_folds_one_full_week(self) -> None:
        bars = [
            bar("2026-08-10", 100, 120, 90, 110, 10),
            bar("2026-08-11", 110, 130, 105, 125, 20),
            bar("2026-08-12", 125, 128, 80, 95, 30),
            bar("2026-08-13", 95, 100, 90, 98, 40),
            bar("2026-08-14", 98, 115, 97, 112, 50),
        ]
        out = resample(bars, "weekly")
        assert len(out) == 1
        w = out[0]
        assert w.open == 100      # 첫 봉의 시가
        assert w.close == 112     # 마지막 봉의 종가
        assert w.high == 130      # 구간 최고
        assert w.low == 80        # 구간 최저
        assert w.volume == 150    # 합계
        assert w.date == "2026-08-14"  # 구간 마지막 거래일

    def test_splits_into_two_weeks(self) -> None:
        bars = [
            bar("2026-08-13", 100, 105, 95, 102, 10),  # 1주차 (목)
            bar("2026-08-14", 102, 108, 100, 107, 20),  # 1주차 (금)
            bar("2026-08-17", 107, 115, 106, 110, 30),  # 2주차 (월)
        ]
        out = resample(bars, "weekly")
        assert [b.date for b in out] == ["2026-08-14", "2026-08-17"]
        assert [b.open for b in out] == [100, 107]
        assert [b.close for b in out] == [107, 110]
        assert [b.volume for b in out] == [30, 30]

    def test_short_week_from_holiday(self) -> None:
        """공휴일로 거래일이 2일뿐인 주도 정상적으로 하나의 봉이 된다."""
        bars = [
            bar("2026-08-13", 100, 105, 95, 102, 10),
            bar("2026-08-14", 102, 108, 100, 107, 20),
        ]
        out = resample(bars, "weekly")
        assert len(out) == 1
        assert out[0].open == 100 and out[0].close == 107 and out[0].volume == 30

    def test_single_bar_week(self) -> None:
        bars = [bar("2026-08-14", 100, 110, 90, 105, 10)]
        out = resample(bars, "weekly")
        assert len(out) == 1
        assert (out[0].open, out[0].high, out[0].low, out[0].close) == (100, 110, 90, 105)


class TestResampleMonthly:
    """월봉은 역월 기준."""

    def test_folds_one_month(self) -> None:
        bars = [
            bar("2026-08-03", 100, 120, 90, 110, 10),
            bar("2026-08-14", 110, 140, 85, 130, 20),
            bar("2026-08-31", 130, 135, 120, 125, 30),
        ]
        out = resample(bars, "monthly")
        assert len(out) == 1
        m = out[0]
        assert (m.open, m.high, m.low, m.close, m.volume) == (100, 140, 85, 125, 60)
        assert m.date == "2026-08-31"

    def test_splits_by_calendar_month(self) -> None:
        bars = [
            bar("2026-08-31", 100, 105, 95, 102, 10),
            bar("2026-09-01", 102, 110, 100, 108, 20),
        ]
        out = resample(bars, "monthly")
        assert [b.date for b in out] == ["2026-08-31", "2026-09-01"]

    def test_year_boundary(self) -> None:
        bars = [
            bar("2026-12-30", 100, 105, 95, 102, 10),
            bar("2027-01-04", 102, 110, 100, 108, 20),
        ]
        out = resample(bars, "monthly")
        assert len(out) == 2


class TestResampleAmount:
    """거래대금은 백필 시 None이다 — 합산이 None을 삼키면 안 된다."""

    def test_sums_when_all_present(self) -> None:
        bars = [
            bar("2026-08-10", 100, 110, 95, 105, 10, 1000),
            bar("2026-08-11", 105, 115, 100, 110, 20, 2000),
        ]
        assert resample(bars, "weekly")[0].amount == 3000

    def test_none_when_any_missing(self) -> None:
        """일부만 있는 합계는 사실이 아니므로 None으로 둔다."""
        bars = [
            bar("2026-08-10", 100, 110, 95, 105, 10, 1000),
            bar("2026-08-11", 105, 115, 100, 110, 20, None),
        ]
        assert resample(bars, "weekly")[0].amount is None

    def test_none_when_all_missing(self) -> None:
        bars = [
            bar("2026-08-10", 100, 110, 95, 105, 10),
            bar("2026-08-11", 105, 115, 100, 110, 20),
        ]
        assert resample(bars, "weekly")[0].amount is None


class TestResampleOrdering:
    """입력이 뒤섞여 와도 결과는 날짜 오름차순이어야 한다."""

    def test_sorts_unordered_input(self) -> None:
        bars = [
            bar("2026-08-14", 102, 108, 100, 107, 20),
            bar("2026-08-10", 100, 105, 95, 102, 10),
        ]
        out = resample(bars, "weekly")
        assert len(out) == 1
        assert out[0].open == 100 and out[0].close == 107

    def test_output_is_ascending(self) -> None:
        bars = [
            bar("2026-09-01", 102, 110, 100, 108, 20),
            bar("2026-08-03", 100, 105, 95, 102, 10),
        ]
        out = resample(bars, "monthly")
        assert [b.date for b in out] == sorted(b.date for b in out)


class TestResampleInvariants:
    """어떤 입력이든 깨지면 안 되는 성질."""

    def test_high_low_bracket_open_close(self) -> None:
        bars = [
            bar("2026-08-10", 100, 120, 90, 110, 10),
            bar("2026-08-11", 110, 130, 105, 125, 20),
            bar("2026-08-12", 125, 128, 80, 95, 30),
        ]
        for tf in ("weekly", "monthly"):
            for b in resample(bars, tf):  # type: ignore[arg-type]
                assert b.high >= max(b.open, b.close)
                assert b.low <= min(b.open, b.close)
                assert b.high >= b.low

    def test_volume_is_conserved(self) -> None:
        bars = [bar(f"2026-08-{d:02d}", 100, 110, 90, 105, d) for d in (3, 4, 5, 10, 11)]
        total = sum(b.volume for b in bars)
        assert sum(b.volume for b in resample(bars, "weekly")) == total
        assert sum(b.volume for b in resample(bars, "monthly")) == total
