# PLAN — krx-stock-charts

> SPEC v1.0 기준 개발 계획서. 작성 2026-08-15, D2(Supabase)·D4 확정 반영 2026-08-15.

## 1. 아키텍처

두 개의 독립된 층이 **Supabase 테이블**로만 만난다. 프론트는 파이프라인을 알지 못하고,
파이프라인은 프론트를 알지 못한다. 계약은 `ksc_` 접두어 테이블 3개의 스키마뿐이다.

```
┌─ 수집 층 (Python) ─────────────────────────────┐
│  pykrx ─► collect ─► resample ─► validate ─►   │  service_role 키 (RLS 우회)
│                       (일→주/월)      │        │──────────┐
│                                    store       │          ▼
└────────────────────────────────────────────────┘   ┌──────────────────┐
                  ▲                                  │  Supabase        │
        GitHub Actions cron (평일 18:00 KST)          │  ksc_tickers     │
                                                     │  ksc_bars        │
┌─ 표현 층 (Next.js) ────────────────────┐            │  ksc_meta        │
│  load ─► indicators(MA·통계)           │◄───────────└──────────────────┘
│       ─► lightweight-charts / table    │   anon 키 (RLS: SELECT만)
└────────────────────────────────────────┘
```

**계약은 Supabase 스키마다.** 두 층은 테이블 3개로만 만난다 — 파이프라인은 웹을 모르고,
웹은 파이프라인을 모른다. 각 층은 상대 없이 테스트된다(파이프라인은 가짜 클라이언트, 웹은 fixture).

**D4 확정의 효과**: 리샘플이 Python 한 곳에만 존재한다. 프론트는 읽어 그리기만 하므로
표현 층의 순수 함수는 지표(MA)·포맷터만 남고, 언어 간 리샘플 구현 불일치 위험이 사라진다.

**D2 재확정(Supabase)의 효과**: 매일 커밋으로 인한 리포 히스토리 누적 문제가 사라지고,
데이터가 갱신돼도 웹을 재배포할 필요가 없다. DB의 CHECK 제약이 OHLC 정합성을 2차로 강제한다.

## 2. 모듈 의존관계

### 수집 층 `pipeline/`

```
config.py          설정 (기간·대상·경로) — 의존 없음
    ▼
models.py          Bar, Ticker 타입 계약 — 의존 없음
    ▼
krx_client.py      pykrx 래퍼 (재시도·딜레이·예외 정규화)   ← 유일한 네트워크 접점
    ▼
universe.py        KOSPI200 종목 리스트 조회        ─┐
    ▼                                                │
collect.py         종목별 일봉 수집 (백필/증분)      ─┤
    ▼                                                │
resample.py        일봉 → 주봉/월봉 (순수 함수)      ─┤  ← TDD 주 대상
    ▼                                                │
validate.py        정합성 검사 (순수 함수)           ─┤  ← TDD 주 대상
    ▼                                                │
store.py           Supabase upsert (멱등)            ─┘  ← TDD 주 대상 (가짜 클라이언트)
    ▼
main.py            CLI: --backfill / --update / --validate
```

`resample.py`·`validate.py`·`store.py`는 **외부 의존이 없는 순수 함수**다 — TDD의 주 대상.
`krx_client.py`만 네트워크에 닿으므로, 테스트에서 이 한 겹만 mock하면 전체가 오프라인 검증된다.

### 표현 층 `web/`

```
lib/types.ts        Bar, Ticker (파이프라인 models.py와 1:1 대응)
    ▼
lib/supabase.ts     anon 키 클라이언트 (읽기 전용)
lib/load.ts         ksc_bars 조회 + lightweight-charts 포맷 변환
lib/indicators.ts   SMA, 기간 통계          ─┐  순수 함수 → Vitest 집중 대상
lib/format.ts       원화·거래량·등락률 포맷  ─┘
    ▼
components/CandleChart.tsx    lightweight-charts 래퍼
components/TickerRail.tsx     검색 + 목록 + 스파크라인
components/QuoteHeader.tsx    종목 헤더
components/StatTiles.tsx      통계 타일
components/DataTable.tsx      시세 표
    ▼
app/page.tsx        상태(종목·주기·기간·보기) 보유, 조합
```

**병렬 작성 지점**: `lib/types.ts`를 먼저 고정하면 5개 컴포넌트는 서로를 몰라도 되므로 동시에 작성할 수 있다.

## 3. 데이터 계약

`docs/SPEC.md §5`가 기준. 스키마 원본은 `supabase/schema.sql` (재실행 안전).

- 파이프라인 출력: `ksc_bars`에 `timeframe`으로 구분해 저장 (`daily`/`weekly`/`monthly`)
- **PK `(ticker, timeframe, d)`가 멱등성의 근거** — 같은 봉을 다시 쓰면 덮어써진다
- **갱신 시 마지막 봉 재계산**: 진행 중인 주·월의 봉은 매일 값이 바뀐다. 증분 갱신은
  일봉을 append한 뒤 **해당 종목의 마지막 주봉·월봉을 다시 계산해 덮어쓴다**. (단순 append 금지)
- **MA 워밍업**: 프론트가 표시 구간 앞 최장 MA 주기만큼을 더 읽어야 첫 봉부터 MA선이 그려진다
  (시안에서 확인). D4 변경 후에도 이 규칙은 유효하다 — 리샘플 위치와 무관하게 지표 계산의 성질이다.

## 4. 수집 전략 — 격자를 어느 방향으로 자를 것인가

수집 대상은 `종목 × 거래일` 격자다. pykrx는 두 방향으로 자를 수 있고, 유리한 쪽이 목표에 따라 다르다.

| 목표 | 필요한 조각 | 종목축 `get_market_ohlcv(from, to, ticker)` | 날짜축 `get_market_ohlcv(date)` | 채택 |
|------|-------------|------|------|------|
| 최초 백필 | 격자 전체 | **200회** | 738회 | 종목축 |
| 매일 갱신 | 마지막 열 1개 | 200회 | **1회** | 날짜축 |

**그래서 두 경로를 모두 구현한다.** `--backfill`은 종목축, `--update`는 날짜축.
하나의 수집 함수를 재사용하려다 매일 200회씩 KRX를 두드리는 쪽이 훨씬 비싼 실수다.

### 두 축이 주는 값이 다르다 (2026-09-20, SPEC F16·D7·D8)

| | 종목축 | 날짜축 |
|---|---|---|
| 가격 | **수정주가** (`adjusted=True` 기본) | **원주가** — pykrx가 이 축에 `adjusted` 인자를 주지 않는다 |
| 거래대금 | **없음** | **있음** |
| 쓰는 곳 | 백필 · 재백필 · 드리프트 점검 | 일일 갱신 · `--fill-amount` |

이 비대칭이 2026-09-19 사고의 뿌리다. 두 가지로 막는다.

1. **거래대금은 덮지 않는다** — `store.bar_rows`가 `amount`가 없는 봉에는 `a` 열을 **아예 넣지 않는다**. PostgREST는 요청 본문에 없는 열을 `ON CONFLICT DO UPDATE` 대상에서 빼므로 기존 값이 남는다. `a`를 보내는 행과 보내지 않는 행은 **다른 요청으로 나눠** 보낸다(PostgREST는 한 배열 안의 키가 같아야 한다).
2. **드리프트 비교에서 최근 5거래일을 뺀다** — 두 계열의 괴리는 최근 며칠에만 생기고 과거는 일치한다. 진짜 소급 변경은 과거 전 구간을 바꾸므로 감지력 손실이 없다.

보존에는 작은 대가가 있다. 주·월봉의 `a`는 일봉 합계인데 구간에 NULL이 하나라도 있으면 합계가 None이 되고, 보존 규칙 때문에 **직전 값이 남는다**. `--fill-amount`가 주·월봉을 SQL로 다시 계산하므로 정합은 거기서 회복된다 — 일봉이 보존되는 한 이 경로로 들어올 일 자체가 드물다.

## 5. 테스트 전략

| 층 | 도구 | 대상 |
|----|------|------|
| 파이프라인 순수 함수 | pytest | `resample.py`(주/월 경계·OHLCV 규칙), `validate.py`(결측·이상치·중복), `store.py`(병합 멱등성) |
| 파이프라인 네트워크 | pytest + mock | `krx_client.py` — 실제 KRX 호출 없이 재시도·예외 경로 검증 |
| 프론트 순수 함수 | Vitest | `indicators.ts`(SMA 워밍업), `format.ts`, `load.ts` |
| 프론트 컴포넌트 | Vitest + Testing Library | 주기 전환·기간 전환·종목 선택 시 렌더 결과 |

**리샘플 테스트가 파이프라인으로 이동**했다(D4). 구현이 Python 하나뿐이므로 언어 간 대조 테스트는 불필요하고,
대신 `resample.py`에 경계 케이스 테스트를 두껍게 둔다 — 주 경계(월요일 시작), 월 경계, 공휴일로 인한
짧은 주, 구간에 봉이 1개뿐인 경우.

## 6. 리스크와 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| pykrx 파손 (KRX 사이트 개편) | 갱신 중단 | 검증 실패 시 쓰기 자체를 하지 않음·Actions 실패 알림. 기존 데이터가 Supabase에 있어 서비스는 계속 동작 |
| 진행 중인 주/월 봉 | 마지막 주/월봉이 낡은 값으로 고정 | 증분 갱신 시 마지막 주봉·월봉 **재계산 후 덮어쓰기** (§3) |
| 수정주가 소급 변경 (액면분할·증자) | 과거 데이터와 불일치 | 주 1회 `--check-drift`가 **T-5거래일 이전 15거래일** 종가를 저장분과 대조, 불일치 시 해당 종목 **3주기 모두 재생성** (SPEC F16·D7) |
| 드리프트 오탐 → 대량 재백필 | 재백필이 거래대금을 지우고 KRX를 28분간 두드린다 | 정산 유예 5거래일(D7)로 오탐을 없애고, `a` 열 보존(D8)으로 재백필이 일어나도 거래대금이 남게 한다. 2026-09-19 실제 발생 — 2,470종목 3년치 거래대금 소실 |
| KOSPI200 정기 변경 | 신규 편입 종목 데이터 없음 | `universe.py`가 매 실행 시 목록을 재조회하고, 신규 티커는 자동으로 3년 백필 대상에 넣는다 |
| 초기 백필 시간 | 200종목 × 딜레이 ≈ 5~10분 | 종목축 수집으로 요청 수를 200회로 억제 (§4) |
| Supabase 무료 한도 | 500MB DB 초과 시 중단 | 약 186,400행 ≈ 40MB 예상으로 여유 있음. 종목·기간 확장 시 재점검 |
| service_role 키 노출 | DB 전체 쓰기 권한 탈취 | 파이프라인·CI에서만 사용. 웹은 anon 키만 쓴다. `.env`는 `.gitignore` 제외 |
| 공휴일·거래정지 | 결측일 오판 | 거래일 기준은 KRX 응답 자체를 신뢰. `validate.py`는 "직전 대비 5거래일 이상 공백"만 경고 |

## 7. 마일스톤

| M | 범위 | 산출물 | 완료 기준 |
|---|------|--------|-----------|
| **M0** | 스캐폴드·종목 유니버스 (F1) | `pipeline/` 게이트, `config.py`, `models.py`, `krx_client.py`, `universe.py`, `store.py`, `supabase/schema.sql` | ruff·mypy·pytest 통과, `ksc_tickers` 200행 적재 |
| **M1** | 3년 백필·리샘플 (F2, F4, F7) | `collect.py`, `resample.py`, `validate.py`, `ksc_bars` 적재 | 전 종목 3주기 생성, 검증 통과, 재실행 멱등 |
| **M2** | 증분 갱신·자동화 (F3) | `main.py --update`, `.github/workflows/daily.yml` | 수동 트리거 1회 성공, 마지막 주/월봉 재계산 확인 |
| **M3** | 프론트 기반 (F5) | `web/` 스캐폴드, `lib/*`, `TickerRail` | Vitest 통과, 종목 검색·선택 동작 |
| **M4** | 차트 (F6) | lightweight-charts 연동, 나머지 컴포넌트 | 일/주/월·기간 전환 동작, DESIGN 시안과 일치 |
| **M5** | 배포·보안 점검 | Vercel 배포, README(EN/KO) | 보안 점검 4단계 완료, 빌드 통과 |

M0~M2가 파이프라인, M3~M4가 프론트, M5가 마감이다. **M2 완료 시점에 실데이터가 확보**되므로
M3부터는 시안의 샘플 데이터가 아닌 실제 시세로 작업한다. 단 M3의 순수 함수는 fixture만 있으면
M2를 기다리지 않고 착수할 수 있다. **M0에서 `ksc_tickers`가 이미 채워져 있어 종목 검색은 지금도 개발 가능하다.**

## 8. 검증 명령

```bash
# 파이프라인 (krx-stock-charts/)
source venv/bin/activate
ruff check . && mypy pipeline/ && pytest tests/ -v

# 프론트 (krx-stock-charts/web/)
npm run lint && npm test && npm run build
```

## 변경 이력

| 일자 | 내용 |
|------|------|
| 2026-08-15 | 최초 작성 |
| 2026-08-15 | SPEC D2 재확정(Supabase) 반영 — §1 아키텍처, §2 `store.py`/`supabase.ts`, §3 계약, §6 리스크 갱신 |
| 2026-08-15 | SPEC D4 확정(파이프라인 사전 계산) 반영 — `resample.py` 추가, `resample.ts` 삭제, 리샘플 테스트 이동, 마지막 주/월봉 재계산 리스크 추가. §4 수집 축 전략 명시(백필은 종목축 200회) |
| 2026-09-20 | SPEC v2.5(F16·D7·D8) 반영 — §4에 「두 축이 주는 값이 다르다」 추가(수정주가·거래대금 비대칭과 두 가지 대응), §6에 드리프트 오탐 리스크 추가 |
