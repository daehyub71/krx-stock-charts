"""pykrx 래퍼 — 파이프라인에서 유일하게 네트워크에 닿는 계층.

여기만 mock하면 나머지 모듈은 오프라인으로 전부 검증된다 (PLAN §2).
KRX 호출은 간헐적으로 빈 응답을 반환하므로 재시도와 딜레이를 이 계층에 둔다.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any, TypeVar

from pipeline import config
from pipeline.models import Bar, MarketCap

T = TypeVar("T")

# 수정주가(D5)는 원주가에 보정계수를 곱해 반올림하므로, 원래 같았던 고가와 종가가
# 1원 어긋나는 일이 생긴다. 2023-08~2026-08 · 200종목 실측에서 역전 폭은 **전부 1원**
# (최대 상대오차 0.0062%)이었다. 이보다 큰 어긋남은 반올림으로 설명되지 않으므로
# 보정하지 않고 validate가 잡도록 그대로 둔다.
ROUNDING_TOLERANCE_WON = 1

# 우선주·스팩 등 저유동성 종목에서는 오차가 호가단위 수준(5~50원)까지 벌어진다.
# 2023-08~2026-08 · 전 종목 2,763개 실측에서 최대 상대오차는 **0.4975%**였다
# (000215 DL우, 38380K LX홀딩스1우 등 13건). 절대값이 아니라 종가 대비 비율로 잡는다.
# 이보다 큰 어긋남은 호가·반올림으로 설명되지 않으므로 보정하지 않고 validate가 잡게 둔다.
OHLC_TOLERANCE_RATIO = 0.01


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
    except KrxError as exc:
        # 원인을 삼키지 않는다 — Actions 로그에서 "왜" 실패했는지 보여야 한다 (2026-08-30)
        print(f"경고: {exc}", file=sys.stderr)
        return set()

    time.sleep(config.REQUEST_DELAY)
    return {str(c) for c in codes}


def diagnose_login() -> None:
    """KRX 로그인 응답을 원시 수준에서 찍는다 — 차단 HTML인지, 타임아웃인지 가르기 위해.

    자격증명·쿠키는 출력하지 않는다. 실패해도 예외를 밖으로 내지 않는다.
    (2026-08-30: Actions 러너에서만 로그인이 실패해 원인 판별용으로 추가)
    """
    import os

    login_id, login_pw = os.getenv("KRX_ID"), os.getenv("KRX_PW")
    if not (login_id and login_pw):
        print("진단: KRX_ID/KRX_PW 없음", file=sys.stderr)
        return
    try:
        import requests
        from pykrx.website.comm import auth

        session = requests.Session()
        t0 = time.time()
        warm = session.get(auth.LOGIN_PAGE, headers={"User-Agent": auth.USER_AGENT}, timeout=15)
        print(
            f"진단: 로그인 페이지 GET status={warm.status_code} "
            f"type={warm.headers.get('content-type')} {time.time() - t0:.1f}s",
            file=sys.stderr,
        )
        payload = {"mbrNm": "", "telNo": "", "di": "", "certType": "", "mbrId": login_id, "pw": login_pw}
        resp = session.post(
            auth.LOGIN_URL,
            data=payload,
            headers={"User-Agent": auth.USER_AGENT, "Referer": auth.LOGIN_PAGE},
            timeout=15,
        )
        body = resp.text[:300].replace("\n", " ")
        print(
            f"진단: 로그인 POST status={resp.status_code} "
            f"type={resp.headers.get('content-type')} bytes={len(resp.content)}",
            file=sys.stderr,
        )
        try:
            data = resp.json()
            print(
                f"진단: JSON _error_code={data.get('_error_code')} "
                f"msg={str(data.get('_error_message'))[:80]}",
                file=sys.stderr,
            )
        except ValueError:
            print(f"진단: JSON 아님 — 본문 앞부분: {body}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — 진단은 어떤 예외도 밖으로 내지 않는다
        print(f"진단: 예외 {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)


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

    1. **종가만 있는 봉**: KRX는 거래정지일이나 장중 범위가 보고되지 않은 날에
       시·고·저가를 0으로 주고 종가만 채운다. 거래량이 0인 날(거래정지)도 있고
       거래량이 있는 날도 있다(실측 1건: 010780 2026-08-13, 거래량 199,329).
       어느 쪽이든 **종가 기준 보합 봉**으로 만든다 — 날짜 구멍을 남기지 않으면서
       "종가는 알지만 장중 범위는 모른다"를 봉으로 표현할 수 있는 최선이다.
    2. **고가·저가 역전**: 수정주가 반올림(1원)이나 저유동성 종목의 호가단위 수준
       (5~50원, 종가 대비 최대 0.4975%)으로 고가가 종가보다 낮게 나온다.
       고가는 정의상 종가보다 낮을 수 없으므로, **KRX가 준 값 안에서** 맞춰 준다.
       허용치를 넘으면 손대지 않는다 — validate가 오류로 잡아야 한다.

    Args:
        o: 시가. h: 고가. low: 저가. c: 종가. v: 거래량.

    Returns:
        정규화된 (시가, 고가, 저가, 종가, 거래량). 봉으로 삼을 수 없으면 None.
    """
    if c <= 0:
        # 상장 전 구간 — 봉이 아니다.
        return None

    if o == 0 and h == 0 and low == 0:
        # 종가만 보고된 날. 거래량은 있는 그대로 보존한다.
        return (c, c, c, c, v)

    if min(o, h, low) <= 0:
        # 일부만 0인 경우는 설명되지 않는다 — 그대로 넘겨 validate가 잡게 한다.
        return (o, h, low, c, v)

    # 절대 허용치(반올림)와 비율 허용치(호가단위) 중 큰 쪽을 쓴다.
    tolerance = max(ROUNDING_TOLERANCE_WON, c * OHLC_TOLERANCE_RATIO)
    hi_need, lo_need = max(o, c), min(o, c)
    if 0 < hi_need - h <= tolerance:
        h = hi_need
    if 0 < low - lo_need <= tolerance:
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


def get_market_caps(date: str, market: str = "ALL") -> dict[str, MarketCap]:
    """하루치 전 종목 시가총액·상장주식수를 **한 번의 호출**로 조회한다 (SPEC F8, v2.1).

    종목마다 부르면 2,800회가 되지만 이 경로는 1회로 끝난다.
    응답 열: 종가·시가총액·거래량·거래대금·상장주식수 (2026-08-29 실측).

    Args:
        date: 조회일 ("YYYYMMDD").
        market: "ALL" / "KOSPI" / "KOSDAQ".

    Returns:
        {티커: MarketCap}. 휴장일이면 빈 dict.

    Raises:
        KrxError: 재시도 후에도 조회에 실패한 경우.
    """
    df = _retry(
        lambda: _stock().get_market_cap_by_ticker(date, market),
        what=f"{date} 전종목 시가총액 조회",
    )
    time.sleep(config.REQUEST_DELAY)

    if df is None or not hasattr(df, "empty") or df.empty:
        return {}
    if "시가총액" not in df.columns or "상장주식수" not in df.columns:
        raise KrxError(f"{date} 시가총액 응답에 필요한 열이 없다: {list(df.columns)}")

    out: dict[str, MarketCap] = {}
    for ticker, row in df.iterrows():
        code = str(ticker)
        cap, shrs = int(row["시가총액"]), int(row["상장주식수"])
        if cap <= 0 or shrs <= 0:  # 거래정지·상장폐지 예정 종목은 0으로 온다
            continue
        out[code] = MarketCap(mktcap=cap, list_shrs=shrs)
    return out


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
