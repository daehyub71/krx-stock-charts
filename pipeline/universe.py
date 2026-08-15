"""KOSPI200 종목 유니버스 구성 (SPEC F1).

`build_universe`는 순수 함수다 — KRX 조회 결과를 인자로 받아 조립만 한다.
네트워크는 `fetch_universe`가 `krx_client`를 통해서만 닿는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from pipeline import krx_client, store
from pipeline.models import Ticker

# KRX 티커는 6자리 영숫자다. 대부분 숫자지만 문자가 섞인 코드도 실재한다
# (예: 0126Z0 삼성에피스홀딩스). 숫자만 허용하면 이런 종목이 조용히 누락된다.
_TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
_WS_RE = re.compile(r"\s+")


def is_valid_ticker(code: object) -> bool:
    """6자리 영숫자(대문자) 티커인지 검증한다.

    Args:
        code: 검사할 값. 문자열이 아니면 False.

    Returns:
        유효하면 True.
    """
    if not isinstance(code, str):
        return False
    return bool(_TICKER_RE.match(code))


def normalize_name(name: str) -> str:
    """종목명의 앞뒤 공백을 제거하고 내부 연속 공백을 하나로 줄인다.

    KRX 응답에는 정렬용 공백이 섞여 오는 경우가 있어, 검색·표시 전에 정리한다.

    Args:
        name: 원본 종목명.

    Returns:
        정리된 종목명.
    """
    return _WS_RE.sub(" ", name).strip()


def build_universe(
    codes: Iterable[str],
    name_of: Mapping[str, str],
    kospi_codes: set[str],
    sector_of: Mapping[str, str],
) -> list[Ticker]:
    """조회 결과를 Ticker 리스트로 조립한다 (순수 함수).

    티커 오름차순으로 정렬한다 — 정렬하지 않으면 KRX 응답 순서가 바뀔 때마다
    커밋 diff가 통째로 요동친다.

    Args:
        codes: 구성 종목 티커 목록 (중복·비정상 값 포함 가능).
        name_of: {티커: 종목명}. 이름이 없는 티커는 제외된다.
        kospi_codes: KOSPI 소속 티커 집합. 여기 없으면 KOSDAQ으로 판정한다.
        sector_of: {티커: 업종명}. 없으면 빈 문자열.

    Returns:
        티커 오름차순으로 정렬된 Ticker 리스트.
    """
    seen: set[str] = set()
    result: list[Ticker] = []

    for code in codes:
        if not is_valid_ticker(code) or code in seen:
            continue

        name = normalize_name(name_of.get(code, ""))
        if not name:
            continue

        seen.add(code)
        result.append(
            Ticker(
                ticker=code,
                name=name,
                market="KOSPI" if code in kospi_codes else "KOSDAQ",
                sector=normalize_name(sector_of.get(code, "")),
            )
        )

    return sorted(result, key=lambda t: t.ticker)


def fetch_universe(date: str) -> list[Ticker]:
    """KRX에서 KOSPI200 유니버스를 조회해 조립한다.

    Args:
        date: 기준일 ("YYYYMMDD").

    Returns:
        Ticker 리스트.

    Raises:
        KrxError: 구성종목 조회에 실패한 경우.
    """
    codes = krx_client.get_kospi200_codes()
    kospi_codes = krx_client.get_market_codes(date, "KOSPI")

    # 종목명·업종을 시장별 1회 호출로 확보한다 (종목당 개별 조회 대비 약 900배 빠르다)
    name_of, sector_of = krx_client.get_market_profile(date, "KOSPI")
    if not all(code in name_of for code in codes):
        kosdaq_names, kosdaq_sectors = krx_client.get_market_profile(date, "KOSDAQ")
        name_of = {**kosdaq_names, **name_of}
        sector_of = {**kosdaq_sectors, **sector_of}

    # 일괄 조회에서 누락된 종목만 개별 보충한다
    missing = [code for code in codes if not name_of.get(code)]
    for code in missing:
        fetched = krx_client.get_ticker_name(code)
        if fetched:
            name_of[code] = fetched

    return build_universe(
        codes=codes,
        name_of=name_of,
        kospi_codes=kospi_codes or set(codes),
        sector_of=sector_of,
    )


def save_universe(client: store.SupabaseLike, tickers: list[Ticker], updated: str) -> int:
    """유니버스를 Supabase `ksc_tickers`에 저장한다 (SPEC D2).

    Args:
        client: Supabase 클라이언트.
        tickers: 저장할 Ticker 리스트.
        updated: 데이터 기준일 ("YYYY-MM-DD").

    Returns:
        저장한 행 수.
    """
    written = store.upsert_tickers(client, tickers)
    store.set_meta(client, "universe", {"updated": updated, "count": written})
    return written
