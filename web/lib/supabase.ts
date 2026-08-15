/**
 * Supabase 클라이언트 — **읽기 전용**.
 *
 * 웹은 anon 키만 쓴다. anon 키는 클라이언트 번들에 노출되지만 RLS가 쓰기를 막으므로
 * 안전하다(실측 확인: INSERT·UPDATE·DELETE 모두 차단). service_role 키는 파이프라인
 * 전용이며 이 디렉토리에 절대 들어오면 안 된다.
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const TICKERS_TABLE = "ksc_tickers";
export const BARS_TABLE = "ksc_bars";
export const META_TABLE = "ksc_meta";

let cached: SupabaseClient | null = null;

/**
 * Supabase 클라이언트를 반환한다 (모듈 수준 캐시).
 *
 * @throws 환경 변수가 없을 때.
 */
export function getSupabase(): SupabaseClient {
  if (cached) return cached;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !key) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY 가 없습니다. .env.local을 확인하세요.",
    );
  }

  cached = createClient(url, key, { auth: { persistSession: false } });
  return cached;
}
