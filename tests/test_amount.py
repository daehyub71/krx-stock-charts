"""amount 모듈 테스트 — 날짜 분할 로직만 검증한다 (DB·네트워크 없이)."""

from __future__ import annotations

from datetime import date

from pipeline.amount import month_chunks, trading_day_candidates


class TestTradingDayCandidates:
    def test_skips_weekends(self) -> None:
        # 2026-08-14는 금요일, 15~16은 주말, 17은 월요일
        days = list(trading_day_candidates(date(2026, 8, 14), date(2026, 8, 17)))
        assert days == ["20260814", "20260817"]

    def test_is_ascending(self) -> None:
        days = list(trading_day_candidates(date(2026, 8, 1), date(2026, 8, 31)))
        assert days == sorted(days)

    def test_single_day_range(self) -> None:
        assert list(trading_day_candidates(date(2026, 8, 14), date(2026, 8, 14))) == ["20260814"]

    def test_weekend_only_range_is_empty(self) -> None:
        assert list(trading_day_candidates(date(2026, 8, 15), date(2026, 8, 16))) == []

    def test_three_years_is_about_780_weekdays(self) -> None:
        days = list(trading_day_candidates(date(2023, 8, 14), date(2026, 8, 14)))
        assert 770 <= len(days) <= 790  # 공휴일은 KRX 응답으로 걸러진다


class TestMonthChunks:
    def test_splits_by_calendar_month(self) -> None:
        chunks = list(month_chunks(date(2026, 1, 15), date(2026, 3, 10)))
        assert chunks == [
            (date(2026, 1, 15), date(2026, 1, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 3, 1), date(2026, 3, 10)),
        ]

    def test_single_month(self) -> None:
        assert list(month_chunks(date(2026, 8, 1), date(2026, 8, 31))) == [
            (date(2026, 8, 1), date(2026, 8, 31))
        ]

    def test_covers_the_whole_range_without_gaps(self) -> None:
        chunks = list(month_chunks(date(2023, 8, 14), date(2026, 8, 14)))
        assert chunks[0][0] == date(2023, 8, 14)
        assert chunks[-1][1] == date(2026, 8, 14)
        for i in range(1, len(chunks)):
            assert (chunks[i][0] - chunks[i - 1][1]).days == 1

    def test_handles_leap_february(self) -> None:
        chunks = list(month_chunks(date(2024, 2, 1), date(2024, 2, 29)))
        assert chunks == [(date(2024, 2, 1), date(2024, 2, 29))]

    def test_crosses_year_boundary(self) -> None:
        chunks = list(month_chunks(date(2025, 12, 20), date(2026, 1, 10)))
        assert len(chunks) == 2
        assert chunks[0][1] == date(2025, 12, 31)


class TestZeroAmountIsNotMissing:
    """거래대금 0과 NULL은 뜻이 다르다.

    거래정지일의 거래대금은 **0으로 알려진 값**이지 미수집이 아니다.
    falsy 검사로 거르면 43,990행이 NULL로 남는다 (2026-08-16 실제 발생).
    """

    def test_zero_is_kept_by_none_check(self) -> None:
        amounts = [0, 100, None]
        kept = [a for a in amounts if a is not None]
        assert kept == [0, 100]

    def test_falsy_check_would_drop_zero(self) -> None:
        """왜 `if bar.amount:` 를 쓰면 안 되는지 남겨 둔다."""
        amounts = [0, 100, None]
        assert [a for a in amounts if a] == [100]
