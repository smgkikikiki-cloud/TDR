/**
 * The one place every public showroom-lineup reader decides whether a
 * `current_market_trims` row is a live, orderable grade today.
 *
 * "current_market_trims" is the name of a table, not a promise: it holds
 * every MarketTrim identity attached to the CURRENTLY SERVING canonical
 * release -- evidence, research and historical identities included -- each
 * stamped with its own lifecycle status by the Vehicle Master release
 * pipeline (tdr_bridge/lifecycle.py) at build time: exactly one of
 * "CURRENT", "HISTORICAL" or "UNVERIFIED". A reader that skips this check,
 * or checks for the legacy lowercase "discontinued" instead, will show a
 * retired or not-yet-approved grade as if it were on sale (this is exactly
 * how Volvo EX40's retired trims kept reappearing on the model page).
 *
 * The check is deliberately a strict, case-sensitive equality: the
 * projector always writes the uppercase literal, and a missing/unknown/
 * lowercase value is never treated as CURRENT by silent fallback -- there is
 * no legacy release format that needs a looser rule here.
 *
 * Admin/history/research surfaces (the Vehicle Editor, ECO/price review
 * tools, retail-lifecycle review, market analytics' historical price
 * banding) intentionally read every status and must NOT filter through
 * this module -- they need the non-current rows to do their job.
 */
export function isCurrentLifecycleStatus(status: unknown): boolean {
  return status === "CURRENT";
}

/** PUBLIC_CURRENT_TRIMS = rows from the active release whose lifecycle
 *  status is CURRENT. The one place both public trim readers
 *  (lib/canonical-data.ts, lib/compare-canonical-data.ts) narrow a raw
 *  current_market_trims result down to what a showroom surface may render,
 *  so the rule is provable without a live database. */
export function filterToCurrentTrims<T extends { status?: unknown }>(rows: readonly T[] | null | undefined): T[] {
  return (rows || []).filter((row) => isCurrentLifecycleStatus(row?.status));
}
