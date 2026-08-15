"""수집 오케스트레이션 — 조회 → 검증 → 리샘플 → 적재 (SPEC F2·F4·F7).

한 종목이 실패해도 나머지는 계속 수집한다. 200종목을 도는 작업에서 한 종목의 실패로
전체가 멈추면 재실행 비용이 너무 크기 때문이다. 실패한 종목은 결과에 모아 보고한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pipeline import krx_client, resample, store, validate
from pipeline.models import TIMEFRAMES, Bar, Ticker


@dataclass
class CollectResult:
    """수집 실행 결과 요약.

    Attributes:
        ok: 성공한 종목 수.
        skipped: 봉이 없어 건너뛴 종목 코드.
        failed: {종목 코드: 실패 사유}.
        rows: 주기별 적재 행 수.
        warnings: 경고 메시지 (적재는 진행됨).
    """

    ok: int = 0
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def total_rows(self) -> int:
        """적재한 전체 행 수."""
        return sum(self.rows.values())


def collect_ticker(
    client: store.SupabaseLike,
    ticker: str,
    fromdate: str,
    todate: str,
) -> dict[str, int]:
    """한 종목의 일봉을 수집해 3주기로 적재한다.

    Args:
        client: Supabase 클라이언트.
        ticker: 6자리 종목 코드.
        fromdate: 시작일 ("YYYYMMDD").
        todate: 종료일 ("YYYYMMDD").

    Returns:
        {주기: 적재 행 수}. 봉이 없으면 빈 dict.

    Raises:
        ValueError: 검증에서 오류가 발견된 경우 (적재하지 않는다).
        KrxError: 조회 실패.
    """
    daily = krx_client.get_ohlcv(ticker, fromdate, todate)
    if not daily:
        return {}

    issues = validate.validate_bars(ticker, daily)
    if validate.has_errors(issues):
        detail = "; ".join(str(i) for i in issues if i.severity is validate.Severity.ERROR)
        raise ValueError(detail)

    written: dict[str, int] = {}
    for timeframe in TIMEFRAMES:
        bars: Sequence[Bar] = resample.resample(daily, timeframe)
        written[timeframe] = store.upsert_bars(client, ticker, timeframe, bars)

    return written


def backfill(
    client: store.SupabaseLike,
    tickers: Sequence[Ticker],
    fromdate: str,
    todate: str,
    progress: bool = True,
) -> CollectResult:
    """전 종목 3년치를 백필한다 (종목축 — PLAN §4: 요청 수 = 종목 수).

    Args:
        client: Supabase 클라이언트.
        tickers: 대상 종목.
        fromdate: 시작일 ("YYYYMMDD").
        todate: 종료일 ("YYYYMMDD").
        progress: 진행 상황을 표준 출력에 표시할지 여부.

    Returns:
        수집 결과 요약.
    """
    result = CollectResult()
    total = len(tickers)

    for i, t in enumerate(tickers, start=1):
        try:
            written = collect_ticker(client, t.ticker, fromdate, todate)
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패로 전체를 멈추지 않는다
            result.failed[t.ticker] = str(exc)[:200]
            status = "실패"
        else:
            if not written:
                result.skipped.append(t.ticker)
                status = "봉 없음"
            else:
                result.ok += 1
                for tf, n in written.items():
                    result.rows[tf] = result.rows.get(tf, 0) + n
                d, w, m = (written.get(tf, 0) for tf in TIMEFRAMES)
                status = f"{d}일 / {w}주 / {m}월"

        if progress:
            print(f"  [{i:3d}/{total}] {t.ticker} {t.name[:12]:<14} {status}", flush=True)

    return result
