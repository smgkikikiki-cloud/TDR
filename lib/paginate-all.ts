/**
 * Page through every row a source can return, never trusting a single read
 * to have gotten everything. PostgREST caps any single request at 1,000 rows
 * regardless of what is asked for, so a source that silently stopped after
 * one page would report a catalogue outgrowing that cap as smaller than it
 * is -- exactly the bug the compare picker exists to not repeat (see
 * lib/canonical-data.ts's allRows(), which the same problem forced on the
 * model read).
 *
 * Import-free like lib/free-compare.ts, so scripts/check-free-compare.ts can
 * exercise the pagination behaviour itself under `node
 * --experimental-strip-types` -- not just assert that some function happens
 * to call `.range()` -- without pulling in the Supabase client setup that
 * lib/compare-canonical-data.ts (its only caller) depends on.
 */
export async function paginateAll<T>(
  fetchPage: (from: number, to: number) => Promise<{ data: T[] | null; error: unknown }>,
  pageSize = 1000,
): Promise<T[]> {
  const rows: T[] = [];
  for (let from = 0; ; from += pageSize) {
    const { data, error } = await fetchPage(from, from + pageSize - 1);
    if (error) throw error;
    rows.push(...(data || []));
    if (!data || data.length < pageSize) return rows;
  }
}
