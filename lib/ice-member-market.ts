/**
 * Ice-backed answer for the member market report (/api/report/market). Used ONLY behind a flag:
 *   - Vercel Preview: on (so the owner can look at it)
 *   - Production: off until TDR_ICE_MEMBER_CUTOVER=approved is set by the owner
 * Tier, window, comparison and quota checks stay in the route, before this runs. This file only produces the rows.
 * model / segment / body_type go through the scoped crosswalk (owner decisions); brand / powertrain / registration_type
 * never needed a crosswalk (they are Ice's own columns).
 */
import { adminDb } from "@/lib/supabase";
import {
  comparisonMarketWindow, compareMarketSliceRows, resolveMarketWindow,
  type MarketComparison, type MarketMovementRow, type MarketPeriodWindow, type MarketSliceRow, type MarketWindow,
} from "@/lib/registration-market";
import {
  getIceMarketSlice, getIceScopedMarketSlice, iceAvailablePeriods, icePeriodTotals, missingIceReportPeriods,
} from "@/lib/ice-market-data";

export const ICE_MEMBER_DIMENSIONS = ["brand", "registration_type", "powertrain", "model", "segment", "body_type"] as const;
export type IceMemberDimension = (typeof ICE_MEMBER_DIMENSIONS)[number];

export function isIceMemberDimension(value: string): value is IceMemberDimension {
  return (ICE_MEMBER_DIMENSIONS as readonly string[]).includes(value);
}

export function iceMemberMarketEnabled(env: Record<string, string | undefined> = process.env): boolean {
  return env.VERCEL_ENV === "preview" || env.TDR_ICE_MEMBER_CUTOVER === "approved";
}

export class IceMemberMarketError extends Error {
  status: number; extra: Record<string, unknown>;
  constructor(status: number, message: string, extra: Record<string, unknown> = {}) {
    super(message); this.status = status; this.extra = extra;
  }
}

const SCOPED: ReadonlySet<string> = new Set(["model", "segment", "body_type"]);

async function sliceFor(dimension: IceMemberDimension, window: MarketPeriodWindow, registrationTypes: string[], limit: number): Promise<MarketSliceRow[]> {
  const filters = registrationTypes.length ? { registrationTypes } : {};
  const rows = SCOPED.has(dimension)
    ? await getIceScopedMarketSlice({ dimension: dimension as "model" | "segment" | "body_type", window, filters, limit })
    : await getIceMarketSlice({ dimension: dimension as "brand" | "registration_type" | "powertrain", window, filters, limit });
  return rows as unknown as MarketSliceRow[];
}

export type IceMemberMarket = {
  period_from: string; period_to: string;
  rows: MarketSliceRow[];
  comparison: { mode: MarketComparison; window: MarketPeriodWindow; rows: MarketSliceRow[]; movement: MarketMovementRow[] } | null;
  trend: Array<{ period: string; total: number }>;
};

export async function buildIceMemberMarket(args: {
  dimension: IceMemberDimension; period: string; window: MarketWindow; comparison: MarketComparison | null;
  registrationTypes: string[]; limit: number; trendMonths: number;
}): Promise<IceMemberMarket> {
  const db = adminDb();
  if (!db) throw new IceMemberMarketError(503, "ยังเชื่อมฐานข้อมูลไม่ได้");
  // One database call gives the month list and every month's total (see icePeriodTotals).
  const totals = await icePeriodTotals(db);
  const available = totals ? [...totals.keys()].sort() : await iceAvailablePeriods(db);
  const current = resolveMarketWindow(args.period, args.window);
  const missing = missingIceReportPeriods(current, available);
  if (missing.length) throw new IceMemberMarketError(409, "ยังไม่มีข้อมูล Ice ครบช่วงนี้", { window: current, missing_periods: missing });

  const queryLimit = args.comparison ? 500 : args.limit;
  const rows = await sliceFor(args.dimension, current, args.registrationTypes, queryLimit);

  let comparison: IceMemberMarket["comparison"] = null;
  if (args.comparison) {
    const previous = comparisonMarketWindow(current, args.comparison);
    const missingPrev = missingIceReportPeriods(previous, available);
    if (missingPrev.length) throw new IceMemberMarketError(409, "ยังไม่มีข้อมูล Ice ครบช่วงที่ใช้เทียบ", { comparison_window: previous, missing_periods: missingPrev });
    const prevRows = await sliceFor(args.dimension, previous, args.registrationTypes, 500);
    comparison = { mode: args.comparison, window: previous, rows: prevRows.slice(0, args.limit), movement: compareMarketSliceRows(prevRows, rows) };
  }

  const trendPeriods = args.trendMonths > 0 ? available.filter((p) => p <= current.to).slice(-args.trendMonths) : [];
  const trend: Array<{ period: string; total: number }> = [];
  // One database call gives every month's total (verified equal to the brand panel's total for all 69 months).
  // Only a registration-type filter needs the slower month-by-month path, because the totals call cannot filter.
  for (const p of trendPeriods) {
    if (totals && !args.registrationTypes.length && totals.has(p)) { trend.push({ period: p, total: totals.get(p) as number }); continue; }
    try {
      const one = await sliceFor("brand", resolveMarketWindow(p, "month"), args.registrationTypes, 1);
      trend.push({ period: p, total: Number(one[0]?.market_total || 0) });
    } catch { /* one missing month must not blank the sparkline */ }
  }
  return { period_from: current.from, period_to: current.to, rows: rows.slice(0, args.limit), comparison, trend };
}

/** Month picker for the member page: one row per Ice month, newest data included. mapped_unit_pct stays null (not measured here). */
export async function iceCoverageRows(): Promise<Array<{ period: string; total_registrations: number; mapped_unit_pct: number | null }>> {
  const db = adminDb();
  if (!db) return [];
  const totals = await icePeriodTotals(db);
  const periods = totals ? [...totals.keys()].sort() : await iceAvailablePeriods(db);
  const out: Array<{ period: string; total_registrations: number; mapped_unit_pct: number | null }> = [];
  for (const p of periods) {
    if (totals?.has(p)) { out.push({ period: p, total_registrations: totals.get(p) as number, mapped_unit_pct: null }); continue; }
    const one = await sliceFor("brand", resolveMarketWindow(p, "month"), [], 1);
    out.push({ period: p, total_registrations: Number(one[0]?.market_total || 0), mapped_unit_pct: null });
  }
  return out;
}
