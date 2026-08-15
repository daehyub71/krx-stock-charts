"""적재 전 정합성 검사 (SPEC F7).

DB에도 동일한 CHECK 제약이 걸려 있다. 여기서 먼저 잡는 이유는 **어느 종목의 어느 날짜가
왜 잘못됐는지 로그로 남기기 위해서**다. DB 제약은 최후의 방어선이고, 이 모듈은 진단이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from pipeline.models import Bar

# 이보다 긴 공백은 경고한다. 연휴·거래정지로 실제 발생할 수 있어 오류는 아니다.
MAX_GAP_DAYS = 10


class Severity(Enum):
    """검사 결과의 심각도."""

    ERROR = "error"      # 적재를 중단해야 하는 문제
    WARNING = "warning"  # 기록만 남기고 진행


@dataclass(frozen=True, slots=True)
class Issue:
    """검사에서 발견된 문제 하나.

    Attributes:
        severity: 심각도.
        ticker: 대상 종목 코드.
        date: 문제가 발생한 거래일. 계열 전체 문제면 빈 문자열.
        message: 사람이 읽을 설명.
    """

    severity: Severity
    ticker: str
    date: str
    message: str

    def __str__(self) -> str:
        where = f" {self.date}" if self.date else ""
        return f"[{self.severity.value}] {self.ticker}{where}: {self.message}"


def validate_bars(ticker: str, bars: Sequence[Bar]) -> list[Issue]:
    """봉 계열의 정합성을 검사한다.

    Args:
        ticker: 종목 코드 (로그 식별용).
        bars: 검사할 봉 리스트 (날짜 오름차순이어야 한다).

    Returns:
        발견된 문제 리스트. 비어 있으면 정상.
    """
    issues: list[Issue] = []

    if not bars:
        return [Issue(Severity.ERROR, ticker, "", "수집된 봉이 없다")]

    seen: set[str] = set()
    previous: Bar | None = None

    for b in bars:
        # 가격·거래량 범위
        if min(b.open, b.high, b.low, b.close) <= 0:
            issues.append(Issue(Severity.ERROR, ticker, b.date, "0 이하의 가격이 있다"))
        if b.volume < 0:
            issues.append(Issue(Severity.ERROR, ticker, b.date, f"거래량이 음수다 ({b.volume})"))
        if b.amount is not None and b.amount < 0:
            issues.append(Issue(Severity.ERROR, ticker, b.date, f"거래대금이 음수다 ({b.amount})"))

        # OHLC 정합성
        if b.high < max(b.open, b.close):
            issues.append(
                Issue(Severity.ERROR, ticker, b.date, f"고가({b.high})가 시가/종가보다 낮다")
            )
        if b.low > min(b.open, b.close):
            issues.append(
                Issue(Severity.ERROR, ticker, b.date, f"저가({b.low})가 시가/종가보다 높다")
            )
        if b.high < b.low:
            issues.append(
                Issue(Severity.ERROR, ticker, b.date, f"고가({b.high})가 저가({b.low})보다 낮다")
            )

        # 중복·정렬
        if b.date in seen:
            issues.append(Issue(Severity.ERROR, ticker, b.date, "같은 날짜가 중복된다"))
        seen.add(b.date)

        if previous is not None:
            if b.date < previous.date:
                issues.append(
                    Issue(
                        Severity.ERROR, ticker, b.date,
                        f"날짜가 역순이다 (직전 {previous.date})",
                    )
                )
            else:
                gap = (date.fromisoformat(b.date) - date.fromisoformat(previous.date)).days
                if gap > MAX_GAP_DAYS:
                    issues.append(
                        Issue(
                            Severity.WARNING, ticker, b.date,
                            f"직전 거래일({previous.date})과 {gap}일 공백",
                        )
                    )

        previous = b

    return issues


def has_errors(issues: Sequence[Issue]) -> bool:
    """적재를 중단해야 하는 문제가 있는지 확인한다."""
    return any(i.severity is Severity.ERROR for i in issues)
