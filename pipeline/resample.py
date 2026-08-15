"""일봉 → 주봉/월봉 리샘플 (SPEC F4, D4).

D4로 이 계산이 파이프라인에만 존재하게 되었다. 구현이 한 벌뿐이라 화면에서 걸러낼
방법이 없으므로, 경계 케이스 테스트를 두껍게 두고 이 모듈을 순수 함수로 유지한다.

묶는 규칙 (SPEC §5):
    시가   = 구간 첫 봉의 시가
    종가   = 구간 마지막 봉의 종가
    고가   = 구간 전체의 최고가
    저가   = 구간 전체의 최저가
    거래량 = 합계
    날짜   = 구간 마지막 거래일
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from pipeline.models import Bar, Timeframe


def _parse(iso: str) -> date:
    """ISO 날짜 문자열을 date로 변환한다."""
    return date.fromisoformat(iso)


def week_start(iso: str) -> str:
    """해당 날짜가 속한 주의 월요일을 반환한다 (ISO 주 기준).

    Args:
        iso: ISO 날짜 문자열 ("YYYY-MM-DD").

    Returns:
        그 주 월요일의 ISO 날짜 문자열.
    """
    d = _parse(iso)
    return (d - timedelta(days=d.weekday())).isoformat()


def _bucket_key(iso: str, timeframe: Timeframe) -> str:
    """봉이 속할 구간의 키를 만든다."""
    if timeframe == "weekly":
        return week_start(iso)
    d = _parse(iso)
    return f"{d.year:04d}-{d.month:02d}"


def _fold(bars: Sequence[Bar]) -> Bar:
    """같은 구간의 봉들을 하나로 접는다.

    거래대금은 구간 전체에 값이 있을 때만 합산한다 — 일부만 더한 합계는
    사실이 아니므로 None으로 둔다 (백필분은 거래대금이 없다).

    Args:
        bars: 날짜 오름차순으로 정렬된, 같은 구간에 속하는 봉들.

    Returns:
        접힌 봉 하나.
    """
    amounts = [b.amount for b in bars]
    total_amount = None if any(a is None for a in amounts) else sum(a or 0 for a in amounts)

    return Bar(
        date=bars[-1].date,
        open=bars[0].open,
        high=max(b.high for b in bars),
        low=min(b.low for b in bars),
        close=bars[-1].close,
        volume=sum(b.volume for b in bars),
        amount=total_amount,
    )


def resample(bars: Sequence[Bar], timeframe: Timeframe) -> list[Bar]:
    """일봉을 지정한 주기로 리샘플한다.

    입력이 정렬되어 있지 않아도 결과는 날짜 오름차순이다.

    Args:
        bars: 일봉 리스트.
        timeframe: "daily"(그대로 반환) / "weekly" / "monthly".

    Returns:
        리샘플된 봉 리스트 (날짜 오름차순).
    """
    if timeframe == "daily":
        return list(bars)

    if not bars:
        return []

    ordered = sorted(bars, key=lambda b: b.date)

    groups: list[list[Bar]] = []
    current_key: str | None = None

    for b in ordered:
        key = _bucket_key(b.date, timeframe)
        if key != current_key:
            groups.append([b])
            current_key = key
        else:
            groups[-1].append(b)

    return [_fold(g) for g in groups]
