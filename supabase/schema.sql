-- krx-stock-charts 스키마
-- 기존 Supabase 프로젝트에 다른 데이터가 있으므로 모든 테이블에 ksc_ 접두어를 붙인다.
-- Supabase 대시보드 → SQL Editor에 붙여넣어 실행한다. 재실행해도 안전하다(멱등).

-- ─────────────────────────────────────────────
-- 종목 메타 (SPEC F1)
-- ─────────────────────────────────────────────
create table if not exists ksc_tickers (
  ticker      text primary key,
  name        text not null,
  market      text not null,
  sector      text not null default '',
  updated_at  timestamptz not null default now(),

  -- KRX 티커는 6자리 영숫자다. 0126Z0(삼성에피스홀딩스)처럼 문자가 섞인 코드가 실재하므로
  -- 숫자로만 제약하면 안 된다.
  constraint ksc_tickers_code_format check (ticker ~ '^[0-9A-Z]{6}$')
);

-- ── 마이그레이션 ──────────────────────────────
-- `create table if not exists`는 이미 있는 테이블에 열을 추가하지 않는다.
-- 열을 늘릴 때는 반드시 여기에 alter를 한 줄 더한다.

-- v2.1 (2026-08-29) F8 — 시가총액·상장주식수. 당일 값만 유지한다(과거 시계열 없음).
-- 하위 krx-signal-briefing이 브리핑 메일의 시세 참고에 읽는다. null = 아직 수집 전.
alter table ksc_tickers add column if not exists mktcap    bigint;
alter table ksc_tickers add column if not exists list_shrs bigint;
alter table ksc_tickers add column if not exists mktcap_d  date;

-- ─────────────────────────────────────────────
-- 봉 데이터 (SPEC F2·F4) — 일/주/월봉을 한 테이블에 timeframe으로 구분
-- 주봉·월봉의 d는 해당 구간의 마지막 거래일이다.
-- ─────────────────────────────────────────────
create table if not exists ksc_bars (
  ticker     text not null references ksc_tickers(ticker) on delete cascade,
  -- 1바이트 코드로 저장한다(D/W/M). 249만 행 규모에서 문자열을 그대로 두면
  -- 본체와 PK 인덱스 양쪽에 5바이트씩 낭비된다.
  timeframe  "char" not null,
  d          date not null,
  o          integer not null,  -- 시가 (원)
  h          integer not null,  -- 고가
  l          integer not null,  -- 저가
  c          integer not null,  -- 종가
  v          bigint  not null,  -- 거래량 (주)
  -- 거래대금: 종목축 조회(백필)에는 없고 날짜축 조회(일일 갱신)에만 있다.
  -- 백필분은 NULL로 남고 M2 이후 갱신되는 봉부터 채워진다.
  a          bigint,            -- 거래대금 (원, nullable)

  primary key (ticker, timeframe, d),

  constraint ksc_bars_timeframe check (timeframe in ('D', 'W', 'M')),

  -- 정합성을 DB가 직접 강제한다. validate.py가 놓쳐도 오염된 행은 저장되지 않는다.
  constraint ksc_bars_positive check (o > 0 and h > 0 and l > 0 and c > 0 and v >= 0 and (a is null or a >= 0)),
  constraint ksc_bars_ohlc_order check (h >= greatest(o, c) and l <= least(o, c) and h >= l)
);

-- 조회용 별도 인덱스는 두지 않는다.
-- PK (ticker, timeframe, d)를 PostgreSQL이 역방향 스캔하므로 `order by d desc`가 그대로 처리된다
-- (EXPLAIN으로 확인: Index Scan Backward using ksc_bars_pkey, 비용 동일).
-- 중복 인덱스는 전 종목 기준 100MB 이상을 낭비한다.

-- ─────────────────────────────────────────────
-- 실행 메타 (데이터 기준일·행 수·마지막 갱신 결과)
-- ─────────────────────────────────────────────
create table if not exists ksc_meta (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);

-- ─────────────────────────────────────────────
-- 투자자별 순매수 (SPEC F14, v2.2 — 2026-08-30)
--
-- **넓은 형태로 둔다.** 투자자별로 행을 나누면 2,700종목 × 5투자자 = 13,500행/일,
-- 1년이면 3.4M행이 된다. ksc_bars가 이미 2.4M행·267MB다. 종목당 한 행이면 1년 985K행,
-- 120일 보존이면 32만 행에 머문다.
--
-- 값은 전부 **순매수거래대금(원)**이다. 순매수거래량은 담지 않는다 — 쓰는 쪽(하위
-- krx-signal-briefing F17)이 금액으로만 본다. 필요해지면 열을 더한다.
--
-- `외국인합계`는 저장하지 않는다. pykrx의 이 엔드포인트가 받지 않는 값이라
-- `foreign_net + foreign_etc_net`으로 읽는 쪽에서 만든다 (2026-08-30 실측).
-- ─────────────────────────────────────────────
create table if not exists ksc_investor_flows (
  d                date   not null,
  ticker           text   not null,
  inst_net         bigint,          -- 기관합계
  foreign_net      bigint,          -- 외국인
  foreign_etc_net  bigint,          -- 기타외국인
  indiv_net        bigint,          -- 개인
  corp_etc_net     bigint,          -- 기타법인
  primary key (d, ticker)
);

-- 하위 프로젝트는 "종목 15개 × 최근 30일"로 읽는다. 그 모양에 맞춘 인덱스.
create index if not exists ksc_investor_flows_ticker_d on ksc_investor_flows (ticker, d desc);

-- ─────────────────────────────────────────────
-- RLS — 읽기는 공개, 쓰기는 service_role만 (service_role은 RLS를 우회한다)
-- 웹은 anon 키로 SELECT만 하므로 별도 쓰기 정책을 만들지 않는다.
-- ─────────────────────────────────────────────
alter table ksc_tickers enable row level security;
alter table ksc_bars    enable row level security;
alter table ksc_meta    enable row level security;
alter table ksc_investor_flows enable row level security;

drop policy if exists ksc_tickers_read on ksc_tickers;
drop policy if exists ksc_bars_read    on ksc_bars;
drop policy if exists ksc_meta_read    on ksc_meta;
drop policy if exists ksc_investor_flows_read on ksc_investor_flows;

create policy ksc_tickers_read on ksc_tickers for select to anon, authenticated using (true);
create policy ksc_bars_read    on ksc_bars    for select to anon, authenticated using (true);
create policy ksc_meta_read    on ksc_meta    for select to anon, authenticated using (true);
-- KRX 공개 시장 데이터다. 공개 읽기가 문제되지 않는다 (해석·판정은 하위 프로젝트에만 있다).
create policy ksc_investor_flows_read on ksc_investor_flows for select to anon, authenticated using (true);
