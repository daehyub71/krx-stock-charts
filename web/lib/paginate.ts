/**
 * Supabase REST 페이지네이션.
 *
 * **Supabase는 응답을 1000행에서 자른다 — 오류 없이 조용히.** `limit(2000)`을 요청해도
 * 1000행만 돌아온다(실측 확인). 좌측 레일의 200종목 스파크라인 조회가 정확히 여기에 걸렸고,
 * 완결성 검사 쿼리까지 잘려 "데이터가 없다"는 오탐을 만들었다.
 *
 * 그래서 대량 조회는 반드시 `range()`로 페이지를 넘긴다. 파이프라인의
 * `store.fetch_daily_since`가 같은 일을 Python 쪽에서 한다.
 */

/** Supabase가 한 응답에 담아주는 최대 행 수. */
export const PAGE_SIZE = 1000;

interface RangeQuery<T> {
  range(from: number, to: number): PromiseLike<{ data: T[] | null; error: { message: string } | null }>;
}

/**
 * 쿼리를 페이지 단위로 끝까지 읽는다.
 *
 * 매 페이지마다 `buildQuery()`를 새로 호출한다 — Supabase 쿼리 빌더는 재사용할 수 없다.
 *
 * @param buildQuery 매번 새 쿼리를 만들어 돌려주는 함수.
 * @param maxRows 이 행 수에 도달하면 멈춘다. 생략하면 전부 읽는다.
 * @returns 모든 페이지를 이어붙인 행 배열.
 * @throws 쿼리가 오류를 보고한 경우.
 */
export async function fetchAllPages<T>(
  buildQuery: () => RangeQuery<T>,
  maxRows?: number,
): Promise<T[]> {
  const out: T[] = [];
  let offset = 0;

  for (;;) {
    const remaining = maxRows === undefined ? PAGE_SIZE : Math.min(PAGE_SIZE, maxRows - out.length);
    if (remaining <= 0) break;

    const { data, error } = await buildQuery().range(offset, offset + remaining - 1);
    if (error) throw new Error(`Supabase 조회 실패: ${error.message}`);

    const rows = data ?? [];
    out.push(...rows);

    // 요청한 만큼 다 못 받았으면 마지막 페이지다.
    if (rows.length < remaining) break;
    offset += rows.length;
  }

  return out;
}
