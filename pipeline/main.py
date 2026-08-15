"""파이프라인 CLI 엔트리포인트.

사용법:
    python -m pipeline.main --universe                    # 종목 리스트 갱신 (M0)
    python -m pipeline.main --backfill                    # 3년 백필 (M1)
    python -m pipeline.main --backfill --limit 5          # 소수 종목으로 시험 실행
    python -m pipeline.main --backfill --date 20260814    # 기준일 지정
    python -m pipeline.main --update                      # 당일 증분 갱신 (M2)
    python -m pipeline.main --update --date 20260814      # 특정 거래일 갱신
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from pipeline import config
from pipeline.models import Ticker


def _default_date() -> str:
    """오늘 날짜를 KRX 조회 형식("YYYYMMDD")으로 반환한다."""
    return datetime.now().strftime("%Y%m%d")


def run_universe(date: str) -> int:
    """종목 유니버스를 조회해 Supabase `ksc_tickers`에 저장한다.

    Args:
        date: 기준일 ("YYYYMMDD").

    Returns:
        프로세스 종료 코드 (0=성공).
    """
    from pipeline import store, universe
    from pipeline.krx_client import KrxError

    if not config.has_krx_credentials():
        print(
            "오류: KRX_ID / KRX_PW 가 없습니다. .env 파일을 확인하세요.\n"
            "      (OHLCV 조회는 자격증명 없이 가능하지만, 종목목록 조회에는 필요합니다.)",
            file=sys.stderr,
        )
        return 2

    try:
        tickers = universe.fetch_universe(date)
    except KrxError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    if not tickers:
        print("오류: 조회된 종목이 없습니다. 기존 데이터를 유지합니다.", file=sys.stderr)
        return 1

    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    try:
        client = store.get_client()
        written = universe.save_universe(client, tickers, updated=iso_date)
    except Exception as exc:  # noqa: BLE001 — 저장 실패는 원인을 그대로 보여준다
        print(f"오류: Supabase 저장 실패: {exc}", file=sys.stderr)
        return 1

    markets: dict[str, int] = {}
    for t in tickers:
        markets[t.market] = markets.get(t.market, 0) + 1
    with_sector = sum(1 for t in tickers if t.sector)

    print(f"저장 완료: Supabase {store.TICKERS_TABLE}")
    print(f"  종목 수   : {written}")
    print(f"  시장 분포 : {markets}")
    print(f"  업종 보유 : {with_sector}/{len(tickers)}")
    print(f"  기준일    : {iso_date}")
    return 0


def run_backfill(date: str, limit: int | None) -> int:
    """전 종목 3년치를 수집해 Supabase에 적재한다 (M1).

    Args:
        date: 기준일 ("YYYYMMDD") — 이 날짜로부터 과거 3년을 수집한다.
        limit: 대상 종목 수 상한. None이면 전체.

    Returns:
        프로세스 종료 코드 (0=성공, 1=일부/전체 실패).
    """
    import time

    from pipeline import collect, store

    try:
        client = store.get_client()
    except Exception as exc:  # noqa: BLE001
        print(f"오류: Supabase 연결 실패: {exc}", file=sys.stderr)
        return 1

    rows = client.table(store.TICKERS_TABLE).select("*").order("ticker").execute()
    tickers = [
        Ticker(r["ticker"], r["name"], r["market"], r.get("sector", "")) for r in rows.data
    ]
    if not tickers:
        print(
            "오류: ksc_tickers가 비어 있습니다. 먼저 --universe 를 실행하세요.",
            file=sys.stderr,
        )
        return 1

    if limit:
        tickers = tickers[:limit]

    start_date = _shift_years(date, -config.BACKFILL_YEARS)
    print(f"백필 대상 {len(tickers)}종목 · 기간 {start_date} ~ {date}")
    print(f"예상 요청 수 {len(tickers)}회 (종목축) · 딜레이 {config.REQUEST_DELAY}초\n")

    began = time.time()
    result = collect.backfill(client, tickers, start_date, date)
    elapsed = time.time() - began

    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    store.set_meta(
        client,
        "backfill",
        {
            "updated": iso_date,
            "from": f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
            "tickers": result.ok,
            "rows": result.rows,
        },
    )

    print(f"\n백필 완료 ({elapsed / 60:.1f}분)")
    print(f"  성공     : {result.ok}종목")
    print(f"  적재 행수 : {result.rows} (합계 {result.total_rows():,})")
    if result.skipped:
        print(f"  봉 없음   : {len(result.skipped)}종목 {result.skipped[:5]}")
    if result.failed:
        print(f"  실패     : {len(result.failed)}종목", file=sys.stderr)
        for code, reason in list(result.failed.items())[:5]:
            print(f"    {code}: {reason}", file=sys.stderr)
        return 1
    return 0


def run_update(date: str) -> int:
    """당일 봉을 갱신하고 마지막 주/월봉을 재계산한다 (M2).

    Args:
        date: 갱신할 거래일 ("YYYYMMDD").

    Returns:
        프로세스 종료 코드 (0=성공/휴장, 1=실패).
    """
    from pipeline import collect, store, update

    try:
        client = store.get_client()
    except Exception as exc:  # noqa: BLE001
        print(f"오류: Supabase 연결 실패: {exc}", file=sys.stderr)
        return 1

    rows = client.table(store.TICKERS_TABLE).select("ticker").order("ticker").execute()
    tickers = [r["ticker"] for r in rows.data]
    if not tickers:
        print("오류: ksc_tickers가 비어 있습니다. 먼저 --universe 를 실행하세요.", file=sys.stderr)
        return 1

    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    print(f"증분 갱신 {iso_date} · 대상 {len(tickers)}종목 (날짜축 1회 조회)")

    try:
        result = update.update_day(client, date, tickers)
    except Exception as exc:  # noqa: BLE001
        print(f"오류: 갱신 실패, 기존 데이터를 유지합니다: {exc}", file=sys.stderr)
        return 1

    if not result.trading_day:
        print("휴장일 — 변경 없음")
        store.set_meta(client, "update", {"updated": iso_date, "tradingDay": False})
        return 0

    # 수정주가 소급 변경 감지 → 해당 종목만 3주기 재생성 (SPEC §6)
    drifted = update.check_drift(client, tickers, date)
    for ticker in drifted:
        start = _shift_years(date, -config.BACKFILL_YEARS)
        try:
            collect.collect_ticker(client, ticker, start, date)
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"{ticker} 재백필 실패: {exc}")
    result.drifted = drifted

    store.set_meta(
        client,
        "update",
        {
            "updated": iso_date,
            "tradingDay": True,
            "tickers": result.updated_tickers,
            "rows": {
                "daily": result.daily_written,
                "weekly": result.weekly_written,
                "monthly": result.monthly_written,
            },
            "refetched": drifted,
        },
    )

    print(f"  일봉 갱신   : {result.daily_written}행 ({result.updated_tickers}종목)")
    print(f"  주봉 재계산 : {result.weekly_written}행")
    print(f"  월봉 재계산 : {result.monthly_written}행")
    if drifted:
        print(f"  수정주가 변경 : {len(drifted)}종목 재백필 {drifted[:5]}")
    if result.missing:
        print(f"  당일 데이터 없음: {len(result.missing)}종목 {result.missing[:5]}")
    for w in result.warnings[:5]:
        print(f"  경고: {w}", file=sys.stderr)
    return 0


def _shift_years(date: str, years: int) -> str:
    """YYYYMMDD 날짜를 지정한 연수만큼 이동한다."""
    from datetime import date as _date

    d = _date(int(date[:4]), int(date[4:6]), int(date[6:]))
    try:
        shifted = d.replace(year=d.year + years)
    except ValueError:  # 2월 29일
        shifted = d.replace(year=d.year + years, day=28)
    return shifted.strftime("%Y%m%d")


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="KRX 주식 데이터 수집 파이프라인")
    parser.add_argument("--universe", action="store_true", help="종목 유니버스 갱신 (M0)")
    parser.add_argument("--backfill", action="store_true", help="3년치 일·주·월봉 백필 (M1)")
    parser.add_argument("--update", action="store_true", help="당일 증분 갱신 (M2)")
    parser.add_argument("--date", default=None, help='기준일 "YYYYMMDD" (기본: 오늘)')
    parser.add_argument("--limit", type=int, default=None, help="대상 종목 수 상한 (시험 실행용)")
    args = parser.parse_args(argv)

    config.load_env()
    date = args.date or _default_date()

    if args.universe:
        code = run_universe(date)
        if code != 0 or not args.backfill:
            return code

    if args.backfill:
        return run_backfill(date, args.limit)

    if args.update:
        return run_update(date)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
