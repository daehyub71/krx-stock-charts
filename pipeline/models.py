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
class InvestorFlow:
    """종목 하나의 하루치 투자자별 **순매수거래대금(원)** (SPEC F14, v2.2).

    pykrx는 투자자 이름을 하나씩만 받으므로 투자자별로 따로 받아 여기에 합친다.

    **None과 0은 다르다.** 그 투자자 표에 종목이 없으면 `None`(안 받았거나 거래가 집계되지 않음),
    실제로 순매수가 0원이면 `0`이다. 0으로 채우면 "거래가 없었다"가 "값이 없다"를 덮는다.

    `외국인합계`는 담지 않는다 — pykrx의 이 엔드포인트가 받지 않는 값이라
    읽는 쪽에서 `foreign_net + foreign_etc_net`으로 만든다 (2026-08-30 실측).
    """

    inst_net: int | None = None  # 기관합계
    foreign_net: int | None = None  # 외국인
    foreign_etc_net: int | None = None  # 기타외국인
    indiv_net: int | None = None  # 개인
    corp_etc_net: int | None = None  # 기타법인


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
class IndexBar:
    """지수 하나의 하루치 (하위 `krx-signal-verify` V12 요청).

    **`Bar`를 쓰지 않는다.** `Bar`의 가격은 `int`인데 지수는 소수점이 있다 —
    6,579.48을 6,579로 저장하면 0.5% 오차가 하위의 **초과수익 계산에 그대로 실린다.**

    지수는 종목이 아니라서 `ksc_bars`에도 못 넣는다: 그 표는 `ksc_tickers` FK와
    `^[0-9A-Z]{6}$` 제약을 갖고 있다.

    Attributes:
        date: 거래일 (ISO "YYYY-MM-DD").
        open: 시가 (지수 포인트).
        high: 고가.
        low: 저가.
        close: 종가.
        volume: 거래량 (주).
        amount: 거래대금 (원). 없을 수 있다.
    """

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    amount: int | None = None


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
