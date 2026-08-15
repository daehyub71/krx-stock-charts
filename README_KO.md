# krx-stock-charts

> 🇺🇸 [English README](README.md)

KOSPI200 종목의 3년치 일봉·주봉·월봉을 한국거래소에서 수집해 Next.js 대시보드로 보여준다.

수집 파이프라인이 KRX에서 일봉을 받아 주봉·월봉까지 미리 계산해 Supabase에 넣고,
웹은 그것을 읽어 차트를 그린다. 두 층은 서로를 호출하지 않는다 — 만나는 곳은 DB 스키마뿐이다.

## 진행 상태

| 마일스톤 | 범위 | 상태 |
|---|---|---|
| M0 | 스캐폴드, 종목 유니버스 | ✅ 완료 |
| M1 | 3년 백필, 리샘플 | ✅ 완료 |
| M2 | 일일 증분 갱신, GitHub Actions | ✅ 완료 |
| M3 | 프론트 기반, Supabase 조회 계층 | ✅ 완료 |
| M4 | 캔들 차트 (lightweight-charts) | 예정 |
| M5 | 배포, 보안 점검 | 예정 |

현재 적재량: 200종목 **182,307행** — 일봉 144,028 / 주봉 30,976 / 월봉 7,303,
2023-08-14 ~ 2026-08-14 구간, 46MB.

## 주요 기능

- **3년치 백필** — KOSPI200 구성 종목을 수정주가로 받아 액면분할·증자로 인한 차트 왜곡을 막는다.
- **주봉·월봉 사전 계산** — 리샘플 구현이 Python 한 곳에만 존재하므로 두 벌이 어긋날 일이 없다.
- **일일 증분 갱신** — `종목 × 거래일` 격자를 종목축이 아니라 **날짜축**으로 자르기 때문에
  KRX 요청 **1회**로 끝난다 (종목축이면 200회).
- **멱등한 쓰기** — 기본키가 `(종목, 주기, 날짜)`라 재실행하면 중복 대신 덮어쓴다.
- **2중 검증** — 어느 종목 어느 날짜가 왜 잘못됐는지 알려주는 Python 검사와,
  오염된 행 자체를 거부하는 PostgreSQL `CHECK` 제약.
- **읽기 전용 웹 접근** — 브라우저는 anon 키만 쓰고, RLS가 모든 쓰기를 막는다.

## 기술 스택

| 층 | 도구 |
|---|---|
| 수집 | Python 3.11, pykrx, pandas |
| 저장 | Supabase (PostgreSQL), 테이블 접두어 `ksc_` |
| 자동화 | GitHub Actions (평일 18:00 KST) |
| 웹 | Next.js 16, TypeScript, Tailwind CSS, lightweight-charts |
| 테스트 | pytest 96개, Vitest 51개 |

## 설치

### 1. 파이프라인

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env              # 값 입력
```

`.env`에 네 가지가 필요하다.

| 키 | 용도 |
|---|---|
| `KRX_ID`, `KRX_PW` | pykrx 1.2.8+는 종목목록 조회에 KRX 계정을 요구한다. OHLCV 조회는 계정 없이 된다. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | 파이프라인 쓰기용. service 키는 RLS를 우회하므로 **브라우저에 절대 넣지 않는다**. |

### 2. 데이터베이스

Supabase SQL 편집기에서 `supabase/schema.sql`을 실행한다. 멱등하므로 다시 돌려도 안전하다.

### 3. 웹

```bash
cd web
npm install
cp .env.local.example .env.local  # NEXT_PUBLIC_SUPABASE_URL + anon 키
npm run dev
```

## 사용법

```bash
python -m pipeline.main --universe                 # 종목 리스트 갱신
python -m pipeline.main --backfill                 # 3년 백필 (약 3분)
python -m pipeline.main --backfill --limit 5       # 소수 종목 시험 실행
python -m pipeline.main --update                   # 당일 증분 갱신
python -m pipeline.main --update --date 20260814   # 특정 거래일
```

GitHub Actions는 평일에 `--universe` 다음 `--update`를 실행한다.
리포지토리 Secrets로 `KRX_ID`, `KRX_PW`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`가 필요하다.

## 테스트

```bash
# 파이프라인
ruff check . && mypy pipeline/ && pytest tests/ -v

# 웹
cd web && npm run lint && npm test && npm run build
```

## 구조

```
pipeline/
  krx_client.py   pykrx 래퍼 — 네트워크에 닿는 유일한 모듈
  universe.py     KOSPI200 구성 종목
  collect.py      조회 → 검증 → 리샘플 → 적재
  resample.py     일봉 → 주봉/월봉 (순수 함수)
  validate.py     정합성 검사 (문제 종목·날짜를 지목한다)
  store.py        Supabase upsert (멱등)
  update.py       증분 갱신, 수정주가 소급 변경 감지
supabase/
  schema.sql      테이블·인덱스·RLS 정책
web/
  lib/types.ts    공유 계약 — pipeline/models.py와 1:1 대응
  lib/load.ts     Supabase 조회 (이동평균 워밍업 포함)
  lib/paginate.ts 1000행 응답 상한 우회
  components/     TickerRail, 차트는 M4에서 추가
docs/
  SPEC.md PLAN.md DESIGN.md TASKS.md
  mockups/        동작하는 디자인 시안과 아키텍처 설명 페이지
```

## 만들면서 배운 것

실제 데이터가 강제한 세 가지다. 두 번째로 틀리기 쉬워서 남겨 둔다.

**티커는 숫자가 아니다.** `0126Z0`(삼성에피스홀딩스)은 실재하는 KOSPI200 구성 종목이다.
`^\d{6}$`로 검증하면 이런 종목이 조용히 사라진다.

**거래정지일은 0으로 온다.** KRX는 거래정지일에 시·고·저가를 0으로 주고 종가만 직전값을 유지한다.
이런 날은 구멍으로 남기지 않고 보합 봉으로 만든다.

**수정주가는 반올림이 어긋난다.** 보정계수를 곱하면 원래 같았던 고가와 종가가 1원 차이로 벌어진다.
3년 × 200종목에서 그 폭은 **항상 정확히 1원**이었기에, 보정 허용치를 1원으로 잡았다.
그보다 큰 어긋남은 반올림이 아니므로 검증이 오류로 잡게 둔다.

## 고지

개인 학습·분석용이다. 투자 자문이 아니며 실시간 시세도 아니다 — 직전 거래일 종가까지만 담는다.

## 라이선스

MIT
