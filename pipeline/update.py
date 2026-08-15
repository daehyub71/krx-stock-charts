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
from pipeline.models import Bar

# 수정주가 소급 변경을 감지할 때 대조할 최근 거래일 수 (SPEC §6)
DRIFT_CHECK_BARS = 20


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


def detect_drift(stored: Sequence[Bar], fresh: Sequence[Bar]) -> bool:
    """수정주가 소급 변경 여부를 판단한다.

    액면분할·증자가 일어나면 KRX가 돌려주는 **과거 수정주가까지 바뀐다**.
    저장분과 새로 받은 값의 같은 날짜 종가가 어긋나면 그 종목은 재백필 대상이다.

    Args:
        stored: DB에 저장된 봉.
        fresh: KRX에서 새로 받은 같은 기간의 봉.

    Returns:
        소급 변경이 감지되면 True.
    """
    fresh_by_date = {b.date: b.close for b in fresh}
    for b in stored:
        other = fresh_by_date.get(b.date)
        if other is not None and other != b.close:
            return True
    return False


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
    for ticker, bar in todays.items():
        issues = validate.validate_bars(ticker, [bar])
        if validate.has_errors(issues):
            result.warnings.append(f"{ticker} 당일 봉 검증 실패, 건너뜀: {issues[0]}")
            continue
        result.daily_written += store.upsert_bars(client, ticker, "daily", [bar])
        result.updated_tickers += 1

    # 3) 진행 중인 주·월 구간을 DB에서 읽어 재계산 (PLAN §3)
    window = tail_window_start(iso_day)
    recent = store.fetch_daily_since(client, window, tickers=sorted(todays.keys()))

    for ticker, bars in recent.items():
        if not bars:
            continue
        in_week = [b for b in bars if resample.week_start(b.date) == resample.week_start(iso_day)]
        in_month = [b for b in bars if b.date[:7] == iso_day[:7]]

        if in_week:
            result.weekly_written += store.upsert_bars(
                client, ticker, "weekly", resample.resample(in_week, "weekly")
            )
        if in_month:
            result.monthly_written += store.upsert_bars(
                client, ticker, "monthly", resample.resample(in_month, "monthly")
            )

    return result


def check_drift(
    client: store.SupabaseLike,
    tickers: Sequence[str],
    todate: str,
    bars: int = DRIFT_CHECK_BARS,
) -> list[str]:
    """수정주가 소급 변경이 일어난 종목을 찾는다.

    Args:
        client: Supabase 클라이언트.
        tickers: 검사할 종목.
        todate: 기준일 ("YYYYMMDD").
        bars: 대조할 최근 거래일 수.

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
