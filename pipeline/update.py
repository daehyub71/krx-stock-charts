"""일일 증분 갱신 (SPEC F3).

백필과 다른 점이 둘 있다.

1. **날짜축 조회**(PLAN §4) — 필요한 건 마지막 열 하나뿐이라 요청 1회로 끝난다.
2. **마지막 주/월봉 재계산** — 진행 중인 주와 달의 봉은 매일 값이 바뀐다.
   일봉만 덧붙이면 마지막 주/월봉이 낡은 값으로 굳으므로, 해당 구간을 다시 접어 덮어쓴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from pipeline import krx_client, resample, store, validate
from pipeline.models import Bar, InvestorFlow, ShortVolume, Ticker

# 수정주가 소급 변경을 감지할 때 끌어올 최근 거래일 수 (SPEC F16)
DRIFT_CHECK_BARS = 20

# 그중 최근 N거래일은 **비교에서 뺀다** — 정산 유예 (SPEC D7, 2026-09-20).
# 일일 갱신은 날짜축(원주가), 이 점검은 종목축(수정주가)이라 최근 며칠 값이 서로 다르게 오는
# 일이 있다. 2026-09-19에 이 차이를 소급 변경으로 읽어 2,762종목 중 2,470종목을 재백필했다.
DRIFT_SETTLE_BARS = 5


@dataclass
class UpdateResult:
    """증분 갱신 결과 요약."""

    trading_day: bool = True
    daily_written: int = 0
    weekly_written: int = 0
    monthly_written: int = 0
    updated_tickers: int = 0
    drifted: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def month_start(iso: str) -> str:
    """해당 날짜가 속한 달의 1일을 반환한다."""
    d = date.fromisoformat(iso)
    return d.replace(day=1).isoformat()


def tail_window_start(iso: str) -> str:
    """마지막 주·월봉을 재계산하는 데 필요한 최소 시작일.

    진행 중인 주의 월요일과 진행 중인 달의 1일 중 이른 쪽이면 충분하다.

    Args:
        iso: 기준일 ("YYYY-MM-DD").

    Returns:
        읽기 시작할 날짜 ("YYYY-MM-DD").
    """
    d = date.fromisoformat(iso)
    monday = d - timedelta(days=d.weekday())
    first = d.replace(day=1)
    return min(monday, first).isoformat()


def detect_drift(
    stored: Sequence[Bar], fresh: Sequence[Bar], settle: int = DRIFT_SETTLE_BARS
) -> bool:
    """수정주가 소급 변경 여부를 판단한다.

    액면분할·증자가 일어나면 KRX가 돌려주는 **과거 수정주가까지 바뀐다**.
    저장분과 새로 받은 값의 같은 날짜 종가가 어긋나면 그 종목은 재백필 대상이다.

    **최근 `settle`거래일은 비교하지 않는다** (SPEC D7). 저장분은 날짜축(원주가)으로 들어오고
    이 비교분은 종목축(수정주가)이라 최근 며칠은 정당하게 다를 수 있다 — 2026-09-20 실측으로
    000020·005930·035720 모두 최근 4~5일만 어긋나고 그 이전 52거래일은 완전히 같았다.
    진짜 소급 변경은 과거 전 구간을 바꾸므로 최근 며칠을 빼도 감지력은 그대로다.

    Args:
        stored: DB에 저장된 봉.
        fresh: KRX에서 새로 받은 같은 기간의 봉.
        settle: 비교에서 뺄 최근 거래일 수.

    Returns:
        소급 변경이 감지되면 True.
    """
    dates = sorted({b.date for b in stored}, reverse=True)
    if len(dates) <= settle:
        return False                      # 비교할 확정 구간이 없다
    cutoff = dates[settle]                # 이 날짜까지만 본다 (최근 settle일 제외)
    fresh_by_date = {b.date: b.close for b in fresh}
    for b in stored:
        if b.date > cutoff:
            continue
        other = fresh_by_date.get(b.date)
        if other is not None and other != b.close:
            return True
    return False


def update_market_caps(
    client: store.SupabaseLike,
    day: str,
    tickers: Sequence[Ticker],
) -> int:
    """시가총액·상장주식수를 갱신한다 (SPEC F8, v2.1). 호출 1회.

    **보조 정보다** — 실패해도 예외를 올리지 않는다. 봉 갱신은 이미 끝났고,
    시총이 하루 비는 것보다 워크플로가 실패해 다음 단계가 멈추는 편이 나쁘다.
    pykrx는 전 종목(약 2,875)을 주지만 `ksc_tickers`에 있는 종목만 저장한다.

    Args:
        client: Supabase 클라이언트.
        day: 기준일 ("YYYYMMDD").
        tickers: 대상 종목 메타 (DB에서 읽은 것 — upsert가 name을 덮어쓰지 않게 함께 보낸다).

    Returns:
        저장한 행 수. 실패하거나 대상이 없으면 0.
    """
    try:
        caps = krx_client.get_market_caps(day)
    except krx_client.KrxError as exc:
        print(f"  시가총액 갱신 실패(무시): {exc}")
        return 0
    if not caps:
        return 0
    basis = date(int(day[:4]), int(day[4:6]), int(day[6:]))
    return store.upsert_market_caps(client, tickers, caps, basis)


def update_investor_flows(client: store.SupabaseLike, day: str) -> int:
    """투자자별 순매수를 갱신한다 (SPEC F14, v2.2). 시장 2 × 투자자 5 = 호출 10회.

    **보조 정보다** — F8(시총)과 같은 원칙으로, 실패해도 예외를 올리지 않는다.
    수급이 하루 비는 것보다 워크플로가 실패해 다음 단계가 멈추는 편이 나쁘다.
    하위 `krx-signal-briefing`은 수급이 없으면 그 층을 생략하고 판정한다.

    Args:
        client: Supabase 클라이언트.
        day: 거래일 ("YYYYMMDD").

    Returns:
        저장한 행 수. 실패하거나 휴장일이면 0.
    """
    merged: dict[str, InvestorFlow] = {}
    for market in krx_client.MARKETS:
        try:
            merged.update(krx_client.get_investor_flows(day, market))
        except krx_client.KrxError as exc:
            print(f"  투자자 순매수 갱신 실패(무시): {market} — {exc}")
            return 0
    if not merged:
        return 0
    d = date(int(day[:4]), int(day[4:6]), int(day[6:]))
    n = store.upsert_investor_flows(client, merged, d)
    store.prune_investor_flows(client, d)
    return n


def update_shorting(client: store.SupabaseLike, day: str) -> int:
    """공매도 거래량·비중을 갱신한다 (SPEC F15 — 하위 `krx-signal-verify` V6b 요청). 호출 2회.

    **보조 정보다** — F8·F14·지수와 같은 원칙으로, 실패해도 예외를 올리지 않는다.
    하위는 이 갈래가 없으면 「생략」으로 표기하고 판정한다 (없어도 되는 층).

    ⚠ **거래일 판정이 먼저다.** 휴장일에 물으면 pykrx가 직전 거래일 자료를 그대로 주므로
    (2026-09-07 실측), 여기서 안 거르면 금요일 값이 일요일 날짜로 저장된다.
    거래일인데 0행이면 로그인 실패다 — 소리를 낸다.

    Args:
        client: Supabase 클라이언트.
        day: 거래일 ("YYYYMMDD").

    Returns:
        저장한 행 수. 휴장일이거나 전부 실패하면 0.
    """
    if not krx_client.is_trading_day(day):
        return 0
    merged: dict[str, ShortVolume] = {}
    for market in krx_client.MARKETS:
        try:
            got = krx_client.get_shorting_volumes(day, market)
        except krx_client.KrxError as exc:
            print(f"  공매도 갱신 실패(무시): {market} — {exc}")
            continue
        if not got:
            print(f"  ⚠ 공매도 {market} 거래일인데 0행 — KRX 로그인을 확인하라")
            continue
        merged.update(got)
    if not merged:
        return 0
    d = date(int(day[:4]), int(day[4:6]), int(day[6:]))
    n = store.upsert_shorting(client, merged, d)
    store.prune_shorting(client, d)
    return n


def update_index_bars(client: store.SupabaseLike, day: str) -> int:
    """지수 일봉을 갱신한다 (2026-09-05 — 하위 `krx-signal-verify` V12 요청). 호출 2회.

    **보조 정보다** — F8(시총)·F14(수급)와 같은 원칙으로, 실패해도 예외를 올리지 않는다.
    지수가 하루 비는 것보다 워크플로가 멈춰 다음 단계가 못 도는 편이 나쁘다.

    ⚠ **0행이 휴장일인지 로그인 실패인지 가른다.** KRX 로그인이 없으면 pykrx가
    **예외 없이 0행**을 준다 (2026-09-05 실측). 거래일인데 0행이면 소리를 낸다 —
    조용히 넘기면 그 갈래가 「정상적으로 비어 있는」 상태로 지나간다.

    Args:
        client: Supabase 클라이언트.
        day: 거래일 ("YYYYMMDD").

    Returns:
        저장한 행 수. 휴장일이거나 전부 실패하면 0.
    """
    if not krx_client.is_trading_day(day):
        return 0
    written = 0
    for market, code in krx_client.INDEXES:
        try:
            bars = krx_client.get_index_ohlcv(code, day, day)
        except krx_client.KrxError as exc:
            print(f"  지수 갱신 실패(무시): {market} — {exc}")
            continue
        if not bars:
            print(f"  ⚠ 지수 {market}({code}) 거래일인데 0행 — KRX 로그인을 확인하라")
            continue
        written += store.upsert_index_bars(client, market, bars)
    return written


def update_day(
    client: store.SupabaseLike,
    day: str,
    tickers: Sequence[str],
) -> UpdateResult:
    """하루치 일봉을 적재하고 마지막 주/월봉을 재계산한다.

    Args:
        client: Supabase 클라이언트.
        day: 갱신할 거래일 ("YYYYMMDD").
        tickers: 대상 종목 코드.

    Returns:
        갱신 결과 요약.
    """
    result = UpdateResult()
    iso_day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    target = set(tickers)

    # 1) 날짜축 1회 조회
    fetched = krx_client.get_ohlcv_by_date(day)
    todays = {t: b for t, b in fetched.items() if t in target}

    if not todays:
        result.trading_day = False
        return result

    result.missing = sorted(target - todays.keys())

    # 2) 당일 일봉 적재 (검증 통과분만)
    # 종목마다 따로 쓰면 요청이 종목 수만큼(2,700회) 나간다. 한 번에 묶는다.
    clean: dict[str, list[Bar]] = {}
    for ticker, bar in todays.items():
        issues = validate.validate_bars(ticker, [bar])
        if validate.has_errors(issues):
            result.warnings.append(f"{ticker} 당일 봉 검증 실패, 건너뜀: {issues[0]}")
            continue
        clean[ticker] = [bar]
    result.daily_written = store.upsert_bars_bulk(client, "daily", clean)
    result.updated_tickers = len(clean)

    # 3) 진행 중인 주·월 구간을 DB에서 읽어 재계산 (PLAN §3)
    window = tail_window_start(iso_day)
    recent = store.fetch_daily_since(client, window, tickers=sorted(todays.keys()))

    # 여기도 종목마다 두 번씩 쓰면 5,400회다. 전 종목을 모아 한 번에 쓴다.
    weekly: dict[str, list[Bar]] = {}
    monthly: dict[str, list[Bar]] = {}
    for ticker, bars in recent.items():
        if not bars:
            continue
        in_week = [b for b in bars if resample.week_start(b.date) == resample.week_start(iso_day)]
        in_month = [b for b in bars if b.date[:7] == iso_day[:7]]
        if in_week:
            weekly[ticker] = list(resample.resample(in_week, "weekly"))
        if in_month:
            monthly[ticker] = list(resample.resample(in_month, "monthly"))
    result.weekly_written = store.upsert_bars_bulk(client, "weekly", weekly)
    result.monthly_written = store.upsert_bars_bulk(client, "monthly", monthly)

    return result


def check_drift(
    client: store.SupabaseLike,
    tickers: Sequence[str],
    todate: str,
    bars: int = DRIFT_CHECK_BARS,
) -> list[str]:
    """수정주가 소급 변경이 일어난 종목을 찾는다.

    최근 `DRIFT_SETTLE_BARS`거래일은 정산 유예로 비교에서 빠진다 (SPEC D7) —
    `bars`가 20이면 실제로 대조하는 구간은 T-5거래일 이전 15거래일이다.

    Args:
        client: Supabase 클라이언트.
        tickers: 검사할 종목.
        todate: 기준일 ("YYYYMMDD").
        bars: 끌어올 최근 거래일 수 (이 중 최근 5일은 비교에서 제외).

    Returns:
        소급 변경이 감지된 종목 코드 리스트.
    """
    d = date.fromisoformat(f"{todate[:4]}-{todate[4:6]}-{todate[6:]}")
    since = (d - timedelta(days=bars * 2)).isoformat()  # 주말·휴일 감안
    fromdate = since.replace("-", "")

    stored = store.fetch_daily_since(client, since, tickers=list(tickers))
    drifted: list[str] = []

    for ticker in tickers:
        have = stored.get(ticker, [])
        if not have:
            continue
        try:
            fresh = krx_client.get_ohlcv(ticker, fromdate, todate)
        except krx_client.KrxError:
            continue
        if detect_drift(have, fresh):
            drifted.append(ticker)

    return drifted
