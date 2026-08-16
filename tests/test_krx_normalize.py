"""normalize_ohlc 테스트 — KRX 원시 행의 실제 특성 처리.

실측 사례를 그대로 테스트로 옮겼다 (2026-08-15 백필에서 발견).
"""

from __future__ import annotations

from pipeline.krx_client import OHLC_TOLERANCE_RATIO, ROUNDING_TOLERANCE_WON, normalize_ohlc


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

    def test_zero_prices_with_volume_also_becomes_flat(self) -> None:
        """거래량이 있어도 시·고·저가가 모두 0이면 보합 봉으로 만든다.

        처음에는 "거래량이 있는데 0이면 이상하다"고 보고 그대로 넘겼는데,
        전 종목 백필에서 실제 사례가 나왔다 (010780 아이에스동서 2026-08-13,
        거래량 199,329). 종가는 실제 값이고 장중 범위만 보고되지 않은 것이므로,
        거래정지일과 같게 다루는 편이 맞다.
        """
        assert normalize_ohlc(0, 0, 0, 100, 500) == (100, 100, 100, 100, 500)


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


class TestLowLiquidityQuirks:
    """우선주·스팩에서 나오는 호가단위 수준의 역전 (2026-08-16 전 종목 백필에서 발견).

    1원 반올림과 달리 오차가 5~50원으로 크지만, 종가 대비로는 0.11~0.50%다.
    고가는 정의상 종가보다 낮을 수 없으므로, KRX가 준 값 안에서 맞춰 준다.
    """

    def test_repairs_one_tick_gap_on_preferred_share(self) -> None:
        """실측: 000215 DL우 2024-01-25 — 종가가 고가보다 50원 높다."""
        assert normalize_ohlc(24850, 24900, 24350, 24950, 1000) == (
            24850, 24950, 24350, 24950, 1000,
        )

    def test_repairs_largest_observed_gap(self) -> None:
        """실측 최대: 38380K LX홀딩스1우 — 40원, 종가 대비 0.4975%."""
        result = normalize_ohlc(7970, 8000, 7950, 8040, 500)
        assert result is not None and result[1] == 8040

    def test_repairs_low_side_too(self) -> None:
        """저가가 종가보다 높은 경우도 같은 허용치로 맞춘다 (10000의 0.1% = 10원)."""
        assert normalize_ohlc(10000, 10200, 10010, 10000, 100) == (
            10000, 10200, 10000, 10000, 100,
        )

    def test_leaves_gap_beyond_ratio_untouched(self) -> None:
        """비율 허용치를 넘는 어긋남은 반올림·호가로 설명되지 않는다 — validate가 잡아야 한다."""
        close = 10000
        high = int(close * (1 - OHLC_TOLERANCE_RATIO * 3))
        result = normalize_ohlc(9000, high, 8000, close, 100)
        assert result is not None
        assert result[1] < max(result[0], result[3])  # 여전히 역전 상태

    def test_ratio_tolerance_covers_all_observed_cases(self) -> None:
        """실측 13건의 최대 상대오차 0.4975%가 허용치 안에 들어와야 한다."""
        assert OHLC_TOLERANCE_RATIO >= 0.005


class TestCloseOnlyBar:
    """거래량은 있는데 시·고·저가만 0으로 오는 경우 (실측 1건)."""

    def test_close_only_bar_becomes_flat(self) -> None:
        """실측: 010780 아이에스동서 2026-08-13 — O/H/L=0, C=18000, V=199329.

        장중 범위는 보고되지 않았지만 종가는 실제 값이다.
        보합 봉으로 만들어 날짜 구멍을 남기지 않고, 거래량은 그대로 보존한다.
        """
        assert normalize_ohlc(0, 0, 0, 18000, 199329) == (18000, 18000, 18000, 18000, 199329)

    def test_keeps_reported_volume(self) -> None:
        result = normalize_ohlc(0, 0, 0, 500, 12345)
        assert result is not None and result[4] == 12345

    def test_partial_zero_is_not_repaired(self) -> None:
        """일부만 0인 경우는 설명되지 않으므로 손대지 않는다."""
        assert normalize_ohlc(100, 0, 90, 105, 10) == (100, 0, 90, 105, 10)
