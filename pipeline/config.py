"""수집 설정과 환경 변수 로딩.

저장은 Supabase가 담당하므로(SPEC D2) 여기에는 파일 경로가 없다.

외부 의존(python-dotenv 등) 없이 표준 라이브러리만으로 `.env`를 읽는다
(워크스페이스 규칙: 최소 의존성 원칙).
"""

from __future__ import annotations

import os
from pathlib import Path

# 프로젝트 루트 (이 파일의 상위 디렉토리)
ROOT = Path(__file__).resolve().parent.parent

# 수집 기간 (년)
BACKFILL_YEARS = 3

# KOSPI200 지수 코드 (KRX 지수 분류)
KOSPI200_INDEX = "1028"

# KRX 서버 부하 방지용 요청 간 딜레이 (초) — SPEC N2
REQUEST_DELAY = 0.6

# 요청 실패 시 재시도 횟수
MAX_RETRIES = 3


def load_env(path: Path | None = None) -> dict[str, str]:
    """`.env` 파일을 읽어 os.environ에 반영하고, 읽은 값을 반환한다.

    이미 환경에 설정된 변수는 덮어쓰지 않는다 (CI의 Secrets 주입이 우선).
    파일이 없으면 조용히 빈 dict를 반환한다 — CI에서는 .env 없이 Secrets만 쓰기 때문이다.

    Args:
        path: `.env` 파일 경로. 생략 시 프로젝트 루트의 `.env`.

    Returns:
        파일에서 읽은 키-값 쌍. 값이 비어 있는 항목은 제외한다.
    """
    target = path or (ROOT / ".env")
    loaded: dict[str, str] = {}

    if not target.is_file():
        return loaded

    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key or not value:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)

    return loaded


def has_krx_credentials() -> bool:
    """KRX 로그인 자격증명이 환경에 준비되었는지 확인한다.

    pykrx 1.2.8+는 종목목록·지수구성종목 조회에 KRX 계정을 요구한다.
    OHLCV 조회는 자격증명 없이도 동작한다.
    """
    return bool(os.getenv("KRX_ID") and os.getenv("KRX_PW"))
