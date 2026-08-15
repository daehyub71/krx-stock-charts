"""pykrx 래퍼 — 파이프라인에서 유일하게 네트워크에 닿는 계층.

여기만 mock하면 나머지 모듈은 오프라인으로 전부 검증된다 (PLAN §2).
KRX 호출은 간헐적으로 빈 응답을 반환하므로 재시도와 딜레이를 이 계층에 둔다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from pipeline import config
from pipeline.models import Bar

T = TypeVar("T")

# 수정주가(D5)는 원주가에 보정계수를 곱해 반올림하므로, 원래 같았던 고가와 종가가
# 1원 어긋나는 일이 생긴다. 2023-08~2026-08 · 200종목 실측에서 역전 폭은 **전부 1원**
# (최대 상대오차 0.0062%)이었다. 이보다 큰 어긋남은 반올림으로 설명되지 않으므로
# 보정하지 않고 validate가 잡도록 그대로 둔다.
ROUNDING_TOLERANCE_WON = 1


class KrxError(RuntimeError):
    """KRX 조회 실패를 나타내는 정규화된 예외."""


def _retry(fn: Callable[[], T], *, what: str, retries: int | None = None) -> T:
    """일시적 실패를 지수 백오프로 재시도한다.

    Args:
        fn: 호출할 함수.
        what: 실패 메시지에 표시할 작업 이름.
        retries: 재시도 횟수. 생략 시 config.MAX_RETRIES.

    Returns:
        fn의 반환값.

    Raises:
        KrxError: 모든 재시도가 실패한 경우.
    """
    attempts = retries if retries is not None else config.MAX_RETRIES
    last: Exception | None = None

    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — pykrx는 예외 종류를 보장하지 않는다
            last = exc
            if i < attempts - 1:
                time.sleep(config.REQUEST_DELAY * (2**i))

    raise KrxError(f"{what} 실패 ({attempts}회 시도): {last}") from last


def _stock() -> Any:
    """pykrx.stock 모듈을 지연 임포트한다.

    임포트 시점에 KRX 로그인 메시지가 출력되므로, .env 로딩 이후로 미룬다.
    """
    from pykrx import stock

    return stock


def get_kospi200_codes() -> list[str]:
    """KOSPI200 구성 종목의 티커 목록을 조회한다.

    Returns:
        6자리 티커 문자열 리스트.

    Raises:
        KrxError: 조회 실패 또는 빈 결과.
    """
    def call() -> list[str]:
        codes = _stock().get_index_portfolio_deposit_file(config.KOSPI200_INDEX)
        if not codes:
            raise ValueError("빈 응답 — KRX 로그인이 필요할 수 있다")
        return [str(c) for c in codes]

    result = _retry(call, what="KOSPI200 구성종목 조회")
    time.sleep(config.REQUEST_DELAY)
    return result


def get_market_codes(date: str, market: str) -> set[str]:
    """특정 시장의 전체 티커 집합을 조회한다.

    Args:
        date: 기준일 ("YYYYMMDD").
        market: "KOSPI" 또는 "KOSDAQ".

    Returns:
        티커 집합. 조회 실패 시 빈 집합 (시장 판정은 보조 정보이므로 치명적이지 않다).
    """
    try:
        codes = _retry(
            lambda: _stock().get_market_ticker_list(date, market=market),
            what=f"{market} 종목목록 조회",
        )
    except KrxError:
        return set()

    time.sleep(config.REQUEST_DELAY)
    return {str(c) for c in codes}


def get_ticker_name(code: str) -> str:
    """종목명을 조회한다.

    Args:
        code: 6자리 티커.

    Returns:
        종목명. 조회 실패 시 빈 문자열.
    """
    try:
        name = _retry(
            lambda: _stock().get_market_ticker_name(code),
            what=f"{code} 종목명 조회",
            retries=2,
        )
    except KrxError:
        return ""

    return str(name) if name else ""


def get_market_profile(date: str, market: str) -> tuple[dict[str, str], dict[str, str]]:
    """시장 전체의 종목명과 업종을 **한 번의 호출**로 조회한다.

    `get_market_ticker_name`을 종목마다 부르면 200종목에 약 285초가 걸린다.
    업종분류 조회는 종목명·업종을 함께 담아 한 번에 돌려주므로(약 0.3초) 이쪽을 쓴다.

    Args:
        date: 기준일 ("YYYYMMDD").
        market: "KOSPI" 또는 "KOSDAQ".

    Returns:
        ({티커: 종목명}, {티커: 업종명}). 조회 실패 시 빈 dict 두 개.
    """
    try:
        df = _retry(
            lambda: _stock().get_market_sector_classifications(date, market),
            what=f"{market} 업종분류 조회",
            retries=2,
        )
    except KrxError:
        return {}, {}

    time.sleep(config.REQUEST_DELAY)

    if df is None or not hasattr(df, "empty") or df.empty:
        return {}, {}

    name_col = next((c for c in ("종목명", "한글명") if c in df.columns), None)
    sector_col = next((c for c in ("업종명", "지수명", "업종") if c in df.columns), None)

    names = (
        {str(idx): str(value) for idx, value in df[name_col].items()} if name_col else {}
    )
    sectors = (
        {str(idx): str(value) for idx, value in df[sector_col].items()} if sector_col else {}
    )
    return names, sectors


def normalize_ohlc(
    o: int, h: int, low: int, c: int, v: int
) -> tuple[int, int, int, int, int] | None:
    """KRX 원시 행을 봉 값으로 정규화한다 (순수 함수).

    두 가지 실제 데이터 특성을 처리한다.

    1. **거래정지일**: KRX는 시·고·저가를 0으로 주고 종가에 직전 값을 유지한다(거래량 0).
       종가 기준 보합 봉으로 만든다 — 날짜 구멍을 남기지 않고, 마지막 알려진 가격을 보존한다.
    2. **수정주가 반올림**: 고가가 시가/종가보다 1원 낮게 나오는 경우가 있다.
       `ROUNDING_TOLERANCE_WON` 이내일 때만 맞춰주고, 그보다 크면 손대지 않는다
       (반올림으로 설명되지 않는 값은 validate가 오류로 잡아야 한다).

    Args:
        o: 시가. h: 고가. low: 저가. c: 종가. v: 거래량.

    Returns:
        정규화된 (시가, 고가, 저가, 종가, 거래량). 봉으로 삼을 수 없으면 None.
    """
    if c <= 0:
        # 상장 전 구간 — 봉이 아니다.
        return None

    if v == 0 and o == 0 and h == 0 and low == 0:
        return (c, c, c, c, 0)

    if min(o, h, low) <= 0:
        # 설명되지 않는 0값 — 그대로 넘겨 validate가 잡게 한다.
        return (o, h, low, c, v)

    hi_need, lo_need = max(o, c), min(o, c)
    if 0 < hi_need - h <= ROUNDING_TOLERANCE_WON:
        h = hi_need
    if 0 < low - lo_need <= ROUNDING_TOLERANCE_WON:
        low = lo_need

    return (o, h, low, c, v)


def get_ohlcv(ticker: str, fromdate: str, todate: str) -> list[Bar]:
    """한 종목의 기간 일봉을 조회한다 (종목축 — PLAN §4).

    수정주가를 적용한다(SPEC D5) — 액면분할·증자로 인한 3년 차트 왜곡을 막는다.
    거래대금은 이 경로에 없으므로 None으로 남는다 (날짜축 조회에만 존재).

    Args:
        ticker: 6자리 종목 코드.
        fromdate: 시작일 ("YYYYMMDD").
        todate: 종료일 ("YYYYMMDD").

    Returns:
        날짜 오름차순 Bar 리스트. 조회 결과가 비면 빈 리스트.

    Raises:
        KrxError: 재시도 후에도 조회에 실패한 경우.
    """
    df = _retry(
        lambda: _stock().get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True),
        what=f"{ticker} 일봉 조회",
    )
    time.sleep(config.REQUEST_DELAY)

    if df is None or not hasattr(df, "empty") or df.empty:
        return []

    bars: list[Bar] = []
    for idx, row in df.iterrows():
        normalized = normalize_ohlc(
            int(row["시가"]), int(row["고가"]), int(row["저가"]),
            int(row["종가"]), int(row["거래량"]),
        )
        if normalized is None:
            continue
        o, h, low, c, v = normalized
        bars.append(
            Bar(
                date=idx.strftime("%Y-%m-%d"),
                open=o, high=h, low=low, close=c, volume=v, amount=None,
            )
        )

    bars.sort(key=lambda b: b.date)
    return bars


def get_ohlcv_by_date(date: str, market: str = "ALL") -> dict[str, Bar]:
    """하루치 전 종목 일봉을 **한 번의 호출**로 조회한다 (날짜축 — PLAN §4).

    일일 갱신은 마지막 열 하나만 필요하므로 이 경로가 요청 1회로 끝난다.
    종목축으로 돌면 종목 수만큼(200회) 필요하다.

    이 경로에는 **거래대금이 포함**된다 (종목축 조회에는 없다).

    Args:
        date: 조회일 ("YYYYMMDD").
        market: "ALL" / "KOSPI" / "KOSDAQ".

    Returns:
        {티커: Bar}. 휴장일이면 빈 dict.

    Raises:
        KrxError: 재시도 후에도 조회에 실패한 경우.
    """
    df = _retry(
        lambda: _stock().get_market_ohlcv_by_ticker(date, market),
        what=f"{date} 전종목 일봉 조회",
    )
    time.sleep(config.REQUEST_DELAY)

    if df is None or not hasattr(df, "empty") or df.empty:
        return {}

    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    has_amount = "거래대금" in df.columns
    out: dict[str, Bar] = {}

    for ticker, row in df.iterrows():
        normalized = normalize_ohlc(
            int(row["시가"]), int(row["고가"]), int(row["저가"]),
            int(row["종가"]), int(row["거래량"]),
        )
        if normalized is None:
            continue
        o, h, low, c, v = normalized
        amount = int(row["거래대금"]) if has_amount else None
        out[str(ticker)] = Bar(
            date=iso, open=o, high=h, low=low, close=c, volume=v, amount=amount
        )

    return out


def is_trading_day(date: str) -> bool:
    """해당 날짜가 거래일인지 확인한다 (휴장일이면 False).

    Args:
        date: 확인할 날짜 ("YYYYMMDD").

    Returns:
        거래일이면 True.
    """
    return bool(get_ohlcv_by_date(date, "KOSPI"))
