"""normalize_ohlc 테스트 — KRX 원시 행의 실제 특성 처리.

실측 사례를 그대로 테스트로 옮겼다 (2026-08-15 백필에서 발견).
"""

from __future__ import annotations

from pipeline.krx_client import ROUNDING_TOLERANCE_WON, normalize_ohlc


class TestNormalBar:
    def test_passes_through_clean_bar(self) -> None:
        assert normalize_ohlc(100, 110, 90, 105, 1000) == (100, 110, 90, 105, 1000)


class TestPreListing:
    def test_zero_close_is_not_a_bar(self) -> None:
        """상장 전 구간은 종가까지 0이다 — 봉이 아니다."""
        assert normalize_ohlc(0, 0, 0, 0, 0) is None

    def test_negative_close_is_not_a_bar(self) -> None:
        assert normalize_ohlc(0, 0, 0, -1, 0) is None


class TestTradingHalt:
    def test_halt_becomes_flat_bar_at_close(self) -> None:
        """실측: 000880 한화 2026-07-30 — O/H/L=0, C=83800, V=0 (거래정지)."""
        assert normalize_ohlc(0, 0, 0, 83800, 0) == (83800, 83800, 83800, 83800, 0)

    def test_flat_bar_satisfies_ohlc_constraints(self) -> None:
        result = normalize_ohlc(0, 0, 0, 83800, 0)
        assert result is not None
        o, h, low, c, _ = result
        assert h >= max(o, c) and low <= min(o, c) and h >= low

    def test_zero_prices_with_volume_is_not_treated_as_halt(self) -> None:
        """거래량이 있는데 가격이 0이면 설명되지 않는다 — 손대지 않고 넘긴다."""
        assert normalize_ohlc(0, 0, 0, 100, 500) == (0, 0, 0, 100, 500)


class TestRoundingRepair:
    def test_repairs_one_won_high_gap(self) -> None:
        """실측: 006040 2023-09-27 — 원주가는 H=C=31000인데 보정 후 1원 어긋남."""
        assert normalize_ohlc(28006, 28187, 27278, 28188, 25847) == (
            28006, 28188, 27278, 28188, 25847,
        )

    def test_repairs_one_won_low_gap(self) -> None:
        assert normalize_ohlc(100, 110, 101, 100, 10) == (100, 110, 100, 100, 10)

    def test_leaves_large_gap_untouched(self) -> None:
        """반올림으로 설명되지 않는 크기는 고치지 않는다 — validate가 잡아야 한다."""
        big = ROUNDING_TOLERANCE_WON + 50
        o, c = 1000, 1000 + big
        result = normalize_ohlc(o, 1000, 900, c, 10)
        assert result == (o, 1000, 900, c, 10)
        assert result[1] < max(result[0], result[3])  # 여전히 역전 상태

    def test_does_not_touch_already_valid_bar(self) -> None:
        assert normalize_ohlc(100, 120, 80, 110, 10) == (100, 120, 80, 110, 10)

    def test_repair_is_exactly_at_tolerance(self) -> None:
        """허용치 경계값은 보정한다."""
        c = 1000
        h = c - ROUNDING_TOLERANCE_WON
        result = normalize_ohlc(900, h, 890, c, 10)
        assert result is not None and result[1] == c
