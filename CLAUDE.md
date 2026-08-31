# CLAUDE.md — krx-stock-charts

워크스페이스 규칙(`../CLAUDE.md`)을 따르며, 아래는 이 프로젝트 고유 규칙이다.

**작업 시작 전 `docs/SPEC.md` → `docs/PLAN.md` → `docs/DESIGN.md` → `docs/TASKS.md` 순으로 읽는다.**

## 개요

KOSPI200 종목의 3년치 일봉을 pykrx로 수집하고, **주봉·월봉을 파이프라인에서 사전 계산**해
**Supabase**에 저장한 뒤, Next.js + lightweight-charts 대시보드에서 캔들 차트를 보여준다.

- 수집 층: `pipeline/` (Python) → Supabase (service_role 키로 쓰기)
- 표현 층: `web/` (Next.js) → Supabase (anon 키로 읽기, RLS가 쓰기 차단)
- 두 층은 `ksc_` 접두어 테이블 3개의 스키마로만 만난다 (PLAN §1)

### Supabase 테이블 (접두어 `ksc_` — 같은 프로젝트에 다른 서비스 테이블이 있다)

| 테이블 | 내용 | 키 |
|--------|------|-----|
| `ksc_tickers` | 종목 메타 | PK `ticker` |
| `ksc_bars` | 일·주·월봉 (`timeframe`으로 구분) | PK `(ticker, timeframe, d)` |
| `ksc_meta` | 실행 메타 (기준일·행 수) | PK `key` |
| `ksc_investor_flows` | **투자자별 순매수거래대금** (F14, v2.2) — 종목당 한 행, 120일 보존 | PK `(d, ticker)` |

스키마 원본은 `supabase/schema.sql` — 재실행해도 안전하다(멱등).
적용은 `SUPABASE_DATABASE_URL` + psycopg로 직접 실행한다 (supabase-py는 DDL 미지원).

## 실행

```bash
source venv/bin/activate

python -m pipeline.main --universe                 # 종목 리스트 → ksc_tickers
python -m pipeline.main --backfill                 # 3년 백필 (약 3분, 200회 요청)
python -m pipeline.main --backfill --limit 5       # 소수 종목 시험 실행
python -m pipeline.main --update                   # 당일 증분 갱신 (1회 요청)
python -m pipeline.main --update --date 20260814   # 특정 거래일
python -m pipeline.main --backfill-flows 45        # 투자자별 순매수 소급 수집 (F14, 일회성)
python -m pipeline.main --check-drift              # 수정주가 소급 변경 검사·재백필 (주 1회, 오래 걸린다)
```

스키마 적용(최초 1회 또는 변경 시):

```bash
python -c "
from pipeline import config; config.load_env()
import os, pathlib, psycopg
with psycopg.connect(os.environ['SUPABASE_DATABASE_URL']) as c:
    c.execute(pathlib.Path('supabase/schema.sql').read_text()); c.commit()
"
```

## 검증 (태스크·마일스톤 완료 시 3종 모두 통과 필수)

```bash
# 파이프라인 (프로젝트 루트)
ruff check .          # 1. 린트
mypy pipeline/        # 2. 타입 체크 (strict)
pytest tests/ -v      # 3. 테스트

# 프론트 (web/)
npm run lint          # 1. 린트
npm test              # 2. 테스트 (vitest)
npm run build         # 3. 빌드 (타입 체크 포함)
```

## 자격증명 (중요)

`.env`는 `.gitignore`로 제외된다 — **절대 커밋 금지**. `.env.example`만 커밋한다.

| 키 | 용도 |
|----|------|
| `KRX_ID` / `KRX_PW` | pykrx 종목목록 조회 (OHLCV는 불필요) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | 파이프라인 쓰기 (RLS 우회). **웹 번들에 절대 넣지 않는다** |
| `SUPABASE_ANON_KEY` | 웹 읽기 전용 (공개되어도 RLS가 쓰기를 막는다) |
| `SUPABASE_DATABASE_URL` | 스키마 적용(DDL) 전용 |

### KRX 로그인

pykrx 1.2.8+는 **종목목록·지수구성종목 조회에 KRX 계정을 요구**한다.
OHLCV 조회는 자격증명 없이도 동작하므로, 증상이 "종목목록만 빈 응답"이면 이걸 의심한다.

- 로컬: `.env`에 `KRX_ID` / `KRX_PW` (→ `.gitignore`로 제외됨, 절대 커밋 금지)
- CI: 리포지토리 Secrets로 주입
- 로더: `pipeline/config.py`의 `load_env()` — 표준 라이브러리만 사용(최소 의존성 원칙),
  이미 설정된 환경변수는 덮어쓰지 않는다(CI 우선)

## 이 프로젝트에서 조심할 것

- **티커는 숫자가 아니다** — `0126Z0`(삼성에피스홀딩스)처럼 문자가 섞인 6자리 코드가 실재한다.
  검증은 `^[0-9A-Z]{6}$`. 숫자로 가정하면 종목이 조용히 누락된다.
- **종목명은 일괄 조회한다** — `get_market_ticker_name()`은 종목당 1회 호출(200종목 ≈ 285초).
  `get_market_sector_classifications()`가 종목명+업종을 함께 0.3초에 반환하므로 이쪽을 쓴다.
- **진행 중인 주/월봉은 매일 바뀐다** — 증분 갱신 시 일봉 append만 하면 마지막 주/월봉이
  낡은 값으로 굳는다. 반드시 재계산해 덮어쓴다 (PLAN §3).
- **MA 워밍업** — 표시 구간만 읽으면 이동평균선 앞부분이 빈다. `표시개수 + 최장 MA주기`만큼 읽는다.
- **KRX 데이터의 두 특성** — 거래정지일은 O/H/L=0·종가 유지로 오고, 수정주가는 반올림으로 고가와 종가가
  1원 어긋날 수 있다. 둘 다 `krx_client.normalize_ohlc`가 처리한다. 허용치는 실측(전부 1원) 기준이므로
  넓히려면 근거를 먼저 재고 넓힌다.
- **`.in()`은 쿼리 문자열에 들어간다** — 티커 2,763개를 한 번에 넣으면 URL 19KB로 400이 난다.
  `SPARKLINE_TICKER_CHUNK`(300)로 나눠 보낸다.
- **OHLC 역전 허용치는 절대·비율 둘 다** — 우선주·스팩은 오차가 종가 대비 0.5%까지 간다
  (`OHLC_TOLERANCE_RATIO`). 넓히려면 실측을 먼저 하고 넓힌다.
- **완결성 검사는 SQL로** — REST로 세면 1000행 상한 때문에 오탐이 난다(실제로 "424개 누락" 오탐 발생, 실제 14개).
- **Supabase REST는 1000행에서 조용히 잘린다** — `limit(2000)`을 줘도 1000행만 오고 오류가 없다.
  대량 조회는 반드시 `range()` 페이지네이션을 쓴다(`store.fetch_daily_since` 참조).
  이걸 모르고 검사 쿼리를 짜면 "데이터가 없다"는 오탐이 난다.
- **DB 제약이 2차 방어선** — `ksc_bars`에 CHECK 제약(가격>0, `h>=max(o,c)`, `l<=min(o,c)`)이 걸려 있다.
  `validate.py`가 놓쳐도 오염 행은 저장이 거부되므로, 적재 실패 시 이 제약부터 의심한다.
- **수정주가는 종목축 조회에만 있다** — `get_market_ohlcv_by_date(..., adjusted=True)`는 종목축이고,
  날짜축 `get_market_ohlcv_by_ticker`에는 `adjusted` 인자가 없어 **원주가**를 준다.
  드리프트 검사를 날짜축으로 바꿔 호출을 2,769→40회로 줄여 봤으나, 액면분할 종목이
  정확히 배수로 어긋나 76종목이 거짓 판정을 받았다(000040: 저장 1,335 · 날짜축 267). **되돌렸다.**
- **드리프트 검사는 일일 갱신에 두지 않는다** — 종목당 1회 × `REQUEST_DELAY` 0.6초 = 대기만 28분이라
  30분 제한에 매번 걸렸다. `--check-drift`로 떼어 **토요일 주 1회** 돈다 (2026-08-31).
  일일 갱신은 이제 **22초**다.
- **워크플로에서 파이썬은 `-u`로 돌린다** — 버퍼링 때문에 30분 잘린 실행의 로그가 통째로 비어
  원인을 못 봤다 (2026-08-31).
- **투자자별 순매수는 투자자 이름을 하나씩만 받는다** — `get_market_net_purchases_of_equities_by_ticker`는
  `외국인합계`를 거부한다(`외국인` + `기타외국인`으로 만든다). 한 번에 그 시장 전 종목을 주므로
  시장2 × 투자자5 = 하루 10회면 끝난다. 종목당 부르면 2,700회다.
- **휴장일에는 pykrx가 `Length mismatch` 로그를 찍는다** — 빈 응답을 처리하다 나오는 내부 메시지이지
  오류가 아니다. `get_investor_flows`는 빈 dict로 넘긴다.
- **`ksc_investor_flows`는 넓은 형태다** — 투자자별로 행을 나누면 1년 3.4M행이 된다.
  `ksc_bars`가 이미 2.4M행·267MB라 종목당 한 행 + 120일 보존으로 32만 행에 묶었다.
- **파일명은 ASCII** — 종목명이 들어가는 파일은 티커로만 명명한다 (Vercel ENOENT 방지).
- **실행 위치** — pip/npm은 반드시 이 디렉토리(또는 `web/`)에서. 워크스페이스 루트 오설치 사례 있음.

## 진행 상태

- **M0~M5 전부 완료** (2026-08-15). 배포됨: https://krx-stock-charts.vercel.app
  - 데이터: **2,763종목**(KOSPI 942 + KOSDAQ 1,821) · `ksc_bars` **2,412,261행**, 267MB
  - 자동화: GitHub Actions `daily.yml` 실행 성공 확인 (평일 18:00 KST cron)
  - 프론트: `web/` Next.js 16 + lightweight-charts 캔들/거래량/MA + 크로스헤어·키보드, Vitest 72개 통과
  - 로컬 확인: `cd web && npm run dev` → http://localhost:3000
  - 리포: `daehyub71/krx-stock-charts` (**public**)
  - ⚠ **미해소**: anon 키가 같은 Supabase 프로젝트의 다른 테이블 12개(`profiles` 포함)를 읽는다.
    배포로 이 키가 공개된 상태. 닫는 SQL은 `docs/TASKS.md` 「미해소 이슈 ②」에 있다.
- **DESIGN §5 확정 완료** (2026-08-15) — 따뜻한 종이 톤 / 적색 상승·청색 하락 / 시안 레이아웃 / lightweight-charts.
  통계 타일 구성(E)만 시안안 기본값이며 M4 전까지 변경 가능. **M4 착수 조건 충족.**
