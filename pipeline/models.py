"""파이프라인 전역의 타입 계약.

SPEC §5 데이터 모델과 1:1로 대응하며, 웹의 `lib/types.ts`도 이 정의를 따른다.
이후 모듈은 모두 이 타입을 기준으로 작성한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Timeframe = Literal["daily", "weekly", "monthly"]

TIMEFRAMES: tuple[Timeframe, ...] = ("daily", "weekly", "monthly")

# DB에는 1바이트 코드로 저장한다. 249만 행 규모에서 'daily'(6바이트)를 그대로 두면
# 본체와 PK 인덱스 양쪽에 5바이트씩 낭비된다 — 전 종목 기준 수십 MB 차이다.
# 코드 안에서는 계속 읽기 좋은 이름을 쓰고, 저장 경계에서만 변환한다.
TIMEFRAME_CODE: dict[Timeframe, str] = {"daily": "D", "weekly": "W", "monthly": "M"}
CODE_TIMEFRAME: dict[str, Timeframe] = {v: k for k, v in TIMEFRAME_CODE.items()}


@dataclass(frozen=True, slots=True)
class Ticker:
    """종목 메타 정보.

    Attributes:
        ticker: 6자리 종목 코드 (예: "005930").
        name: 종목명 (예: "삼성전자").
        market: 소속 시장 ("KOSPI" 또는 "KOSDAQ").
        sector: 업종명. 조회 실패 시 빈 문자열.
    """

    ticker: str
    name: str
    market: str
    sector: str = ""

    def to_json(self) -> dict[str, str]:
        """JSON 직렬화용 dict로 변환한다."""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "market": self.market,
            "sector": self.sector,
        }


@dataclass(frozen=True, slots=True)
class MarketCap:
    """종목 하나의 시가총액·상장주식수 (SPEC F8, v2.1).

    당일 값만 쓴다 — 과거 시계열은 저장하지 않는다. 기준일은 저장할 때 함께 넣는다.

    Attributes:
        mktcap: 시가총액 (원).
        list_shrs: 상장주식수 (주).
    """

    mktcap: int
    list_shrs: int


@dataclass(frozen=True, slots=True)
class Bar:
    """하나의 봉(캔들).

    주봉·월봉의 `date`는 해당 구간의 마지막 거래일이다 (SPEC §5).

    Attributes:
        date: 거래일 (ISO 형식 "YYYY-MM-DD").
        open: 시가 (원).
        high: 고가 (원).
        low: 저가 (원).
        close: 종가 (원).
        volume: 거래량 (주).
        amount: 거래대금 (원). 종목축 조회(백필)에는 없으므로 None일 수 있다.
    """

    date: str
    open: int
    high: int
    low: int
    close: int
    volume: int
    amount: int | None = None

    def to_json(self) -> dict[str, str | int | None]:
        """JSON 직렬화용 dict로 변환한다 (SPEC §5의 축약 키 사용)."""
        return {
            "d": self.date,
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "v": self.volume,
            "a": self.amount,
        }

    @staticmethod
    def from_json(raw: dict[str, str | int | None]) -> Bar:
        """축약 키 dict에서 Bar를 복원한다."""
        amount = raw.get("a")
        return Bar(
            date=str(raw["d"]),
            open=int(raw["o"]),  # type: ignore[arg-type]
            high=int(raw["h"]),  # type: ignore[arg-type]
            low=int(raw["l"]),  # type: ignore[arg-type]
            close=int(raw["c"]),  # type: ignore[arg-type]
            volume=int(raw["v"]),  # type: ignore[arg-type]
            amount=None if amount is None else int(amount),
        )
