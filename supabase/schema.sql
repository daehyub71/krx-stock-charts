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

-- ─────────────────────────────────────────────
-- 봉 데이터 (SPEC F2·F4) — 일/주/월봉을 한 테이블에 timeframe으로 구분
-- 주봉·월봉의 d는 해당 구간의 마지막 거래일이다.
-- ─────────────────────────────────────────────
create table if not exists ksc_bars (
  ticker     text not null references ksc_tickers(ticker) on delete cascade,
  timeframe  text not null,
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

  constraint ksc_bars_timeframe check (timeframe in ('daily', 'weekly', 'monthly')),

  -- 정합성을 DB가 직접 강제한다. validate.py가 놓쳐도 오염된 행은 저장되지 않는다.
  constraint ksc_bars_positive check (o > 0 and h > 0 and l > 0 and c > 0 and v >= 0 and (a is null or a >= 0)),
  constraint ksc_bars_ohlc_order check (h >= greatest(o, c) and l <= least(o, c) and h >= l)
);

-- 차트 조회 패턴: 특정 종목·주기의 최근 N봉을 날짜 역순으로 읽는다.
create index if not exists ksc_bars_lookup on ksc_bars (ticker, timeframe, d desc);

-- ─────────────────────────────────────────────
-- 실행 메타 (데이터 기준일·행 수·마지막 갱신 결과)
-- ─────────────────────────────────────────────
create table if not exists ksc_meta (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);

-- ─────────────────────────────────────────────
-- RLS — 읽기는 공개, 쓰기는 service_role만 (service_role은 RLS를 우회한다)
-- 웹은 anon 키로 SELECT만 하므로 별도 쓰기 정책을 만들지 않는다.
-- ─────────────────────────────────────────────
alter table ksc_tickers enable row level security;
alter table ksc_bars    enable row level security;
alter table ksc_meta    enable row level security;

drop policy if exists ksc_tickers_read on ksc_tickers;
drop policy if exists ksc_bars_read    on ksc_bars;
drop policy if exists ksc_meta_read    on ksc_meta;

create policy ksc_tickers_read on ksc_tickers for select to anon, authenticated using (true);
create policy ksc_bars_read    on ksc_bars    for select to anon, authenticated using (true);
create policy ksc_meta_read    on ksc_meta    for select to anon, authenticated using (true);
