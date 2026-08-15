"""validate 모듈 테스트 — 적재 전 정합성 검사 (SPEC F7)."""

from __future__ import annotations

from pipeline.models import Bar
from pipeline.validate import Severity, validate_bars


def bar(date: str, o: int = 100, h: int = 110, low: int = 90, c: int = 105, v: int = 10) -> Bar:
    """테스트용 Bar 생성 헬퍼 — 기본값은 정상 봉."""
    return Bar(date=date, open=o, high=h, low=low, close=c, volume=v)


def errors(issues: list[object]) -> list[object]:
    return [i for i in issues if getattr(i, "severity", None) == Severity.ERROR]


class TestValidClean:
    def test_no_issues_for_clean_series(self) -> None:
        bars = [bar("2026-08-10"), bar("2026-08-11"), bar("2026-08-12")]
        assert validate_bars("005930", bars) == []

    def test_empty_series_is_an_error(self) -> None:
        """빈 결과는 조용히 넘기면 안 된다 — 수집 실패의 신호다."""
        issues = validate_bars("005930", [])
        assert len(errors(issues)) == 1


class TestPriceSanity:
    def test_zero_price_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-10", o=0)])
        assert errors(issues)

    def test_negative_price_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-10", c=-5)])
        assert errors(issues)

    def test_high_below_open_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-10", o=120, h=110, low=90, c=105)])
        assert errors(issues)

    def test_low_above_close_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-10", o=100, h=110, low=108, c=105)])
        assert errors(issues)

    def test_high_below_low_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-10", o=100, h=95, low=99, c=100)])
        assert errors(issues)

    def test_negative_volume_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-10", v=-1)])
        assert errors(issues)

    def test_zero_volume_is_allowed(self) -> None:
        """거래정지일은 거래량 0으로 나온다 — 정상이다."""
        assert validate_bars("005930", [bar("2026-08-10", v=0)]) == []


class TestDuplicatesAndOrder:
    def test_duplicate_date_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-10"), bar("2026-08-10")])
        assert errors(issues)

    def test_unsorted_dates_is_error(self) -> None:
        issues = validate_bars("005930", [bar("2026-08-12"), bar("2026-08-10")])
        assert errors(issues)


class TestGapWarning:
    def test_long_gap_is_warning_not_error(self) -> None:
        """연휴·거래정지로 공백이 생길 수 있으므로 경고에 그친다."""
        issues = validate_bars("005930", [bar("2026-08-03"), bar("2026-08-31")])
        assert issues
        assert not errors(issues)
        assert all(i.severity == Severity.WARNING for i in issues)

    def test_normal_weekend_gap_is_silent(self) -> None:
        """금요일 → 월요일 3일 공백은 정상이다."""
        assert validate_bars("005930", [bar("2026-08-14"), bar("2026-08-17")]) == []


class TestIssueContent:
    def test_issue_names_the_ticker_and_date(self) -> None:
        """로그만 보고 어느 종목 어느 날짜인지 알 수 있어야 한다."""
        issues = validate_bars("005930", [bar("2026-08-10", o=0)])
        text = str(issues[0])
        assert "005930" in text and "2026-08-10" in text
