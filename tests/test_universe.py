"""universe 모듈 테스트 — KRX 네트워크 없이 순수 로직만 검증한다."""

from __future__ import annotations

import pytest

from pipeline.models import Ticker
from pipeline.universe import (
    build_universe,
    is_valid_ticker,
    normalize_name,
)


class TestIsValidTicker:
    """티커 형식 검증."""

    @pytest.mark.parametrize("code", ["005930", "000660", "373220"])
    def test_valid_six_digit_codes(self, code: str) -> None:
        assert is_valid_ticker(code) is True

    @pytest.mark.parametrize("code", ["0126Z0", "00593A", "A00088"])
    def test_accepts_alphanumeric_codes(self, code: str) -> None:
        """KRX는 문자가 섞인 6자리 코드도 쓴다.

        실제 사례: 0126Z0 = 삼성에피스홀딩스 (2026-08-14 KOSPI200 구성종목).
        숫자만 허용하면 이런 종목이 조용히 누락된다.
        """
        assert is_valid_ticker(code) is True

    @pytest.mark.parametrize(
        "code",
        ["5930", "0059300", "", "  ", "005-30", "00593z", "005 30"],
    )
    def test_rejects_malformed_codes(self, code: str) -> None:
        assert is_valid_ticker(code) is False

    def test_rejects_non_string(self) -> None:
        assert is_valid_ticker(None) is False  # type: ignore[arg-type]


class TestNormalizeName:
    """종목명 정리 — KRX 응답에는 앞뒤 공백과 중복 공백이 섞여 온다."""

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalize_name("  삼성전자  ") == "삼성전자"

    def test_collapses_inner_whitespace(self) -> None:
        assert normalize_name("LG  에너지솔루션") == "LG 에너지솔루션"

    def test_handles_empty(self) -> None:
        assert normalize_name("") == ""
        assert normalize_name("   ") == ""


class TestBuildUniverse:
    """전 종목 목록 → Ticker 리스트 조립."""

    def test_builds_tickers_with_names_and_market(self) -> None:
        result = build_universe(
            codes=["005930", "000660"],
            name_of={"005930": "삼성전자", "000660": "SK하이닉스"},
            kospi_codes={"005930", "000660"},
            sector_of={"005930": "전기전자", "000660": "전기전자"},
        )
        assert result == [
            Ticker("000660", "SK하이닉스", "KOSPI", "전기전자"),
            Ticker("005930", "삼성전자", "KOSPI", "전기전자"),
        ]

    def test_sorted_by_ticker_for_stable_diffs(self) -> None:
        """정렬이 없으면 KRX 응답 순서가 바뀔 때마다 커밋 diff가 요동친다."""
        result = build_universe(
            codes=["373220", "005930", "000660"],
            name_of={"373220": "LG에너지솔루션", "005930": "삼성전자", "000660": "SK하이닉스"},
            kospi_codes={"373220", "005930", "000660"},
            sector_of={},
        )
        assert [t.ticker for t in result] == ["000660", "005930", "373220"]

    def test_removes_duplicate_codes(self) -> None:
        result = build_universe(
            codes=["005930", "005930", "000660"],
            name_of={"005930": "삼성전자", "000660": "SK하이닉스"},
            kospi_codes={"005930", "000660"},
            sector_of={},
        )
        assert [t.ticker for t in result] == ["000660", "005930"]

    def test_drops_malformed_codes(self) -> None:
        result = build_universe(
            codes=["005930", "BAD", "", "12345"],
            name_of={"005930": "삼성전자"},
            kospi_codes={"005930"},
            sector_of={},
        )
        assert [t.ticker for t in result] == ["005930"]

    def test_drops_codes_without_name(self) -> None:
        """종목명을 못 얻은 종목은 화면에서 식별 불가하므로 제외한다."""
        result = build_universe(
            codes=["005930", "999999"],
            name_of={"005930": "삼성전자"},
            kospi_codes={"005930", "999999"},
            sector_of={},
        )
        assert [t.ticker for t in result] == ["005930"]

    def test_marks_non_kospi_as_kosdaq(self) -> None:
        result = build_universe(
            codes=["005930", "247540"],
            name_of={"005930": "삼성전자", "247540": "에코프로비엠"},
            kospi_codes={"005930"},
            sector_of={},
        )
        markets = {t.ticker: t.market for t in result}
        assert markets == {"005930": "KOSPI", "247540": "KOSDAQ"}

    def test_handles_full_market_scale(self) -> None:
        """전 종목(약 2,763개) 규모에서도 정렬·중복 제거가 유지된다."""
        codes = [f"{i:06d}" for i in range(3000)]
        result = build_universe(
            codes=codes + codes[:500],  # 중복 500개 섞음
            name_of={c: f"종목{c}" for c in codes},
            kospi_codes=set(codes[:900]),
            sector_of={},
        )
        assert len(result) == 3000
        assert [t.ticker for t in result] == sorted(codes)
        assert sum(1 for t in result if t.market == "KOSPI") == 900

    def test_missing_sector_becomes_empty_string(self) -> None:
        result = build_universe(
            codes=["005930"],
            name_of={"005930": "삼성전자"},
            kospi_codes={"005930"},
            sector_of={},
        )
        assert result[0].sector == ""

    def test_normalizes_names(self) -> None:
        result = build_universe(
            codes=["373220"],
            name_of={"373220": "  LG  에너지솔루션 "},
            kospi_codes={"373220"},
            sector_of={},
        )
        assert result[0].name == "LG 에너지솔루션"

    def test_empty_input_returns_empty_list(self) -> None:
        assert build_universe(codes=[], name_of={}, kospi_codes=set(), sector_of={}) == []
