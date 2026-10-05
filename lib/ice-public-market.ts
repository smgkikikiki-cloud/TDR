/**
 * Market Track M4 -- the Ice-backed equivalent of `lib/public-market.ts`'s
 * `getPublicMarket`. NOT wired into `app/market/page.tsx` or `app/page.tsx` in
 * this PR (M5 performs that cutover) -- this module exists to prove the new
 * engine can produce the frozen `PublicMarket` shape.
 *
 * The top-8/others/movers/trend algorithm itself lives in
 * `lib/ice-market-engine.ts`'s `assemblePublicMarket` (pure, unit-tested
 * against synthetic fixtures in scripts/check-ice-market-engine.ts with no
 * database); this module is the thin I/O wrapper that fetches rows and calls
 * it, exactly the split `lib/registration-market.ts` (pure) /
 * `lib/public-market.ts` (I/O) already uses.
 *
 * Of the legacy PUBLIC_DIMENSIONS (brand, powertrain, body_type, segment,
 * origin_country, oem_group), only the first four have a defined Ice/TDR
 * source in VEHICLE_DB_V3.md §14.3. origin_country and oem_group are
 * deliberately unsupported here -- see IceMarketDimensionError.
 */
import { adminDb } from "@/lib/supabase";
import { resolveMarketWindow, shiftReportPeriod, type MarketSliceRow } from "@/lib/registration-market";
import { PUBLIC_BRAND_LIMIT, PUBLIC_TREND_MONTHS, type PublicMarket } from "@/lib/public-market";
import { getIceMarketSlice, latestIcePeriod, IceMarketDimensionError, type IceMarketDimension } from "@/lib/ice-market-data";
import { assemblePublicMarket } from "@/lib/ice-market-engine";

export type IcePublicDimension = "brand" | "powertrain" | "body_type" | "segment";

const ICE_PUBLIC_DIMENSIONS: ReadonlySet<string> = new Set(["brand", "powertrain", "body_type", "segment"]);

export function isIcePublicDimension(value: string): value is IcePublicDimension {
  return ICE_PUBLIC_DIMENSIONS.has(value);
}

function shortIcePeriod(period: string): string {
  return period.slice(0, 7);
}

async function icePeriodTotal(
  db: NonNullable<ReturnType<typeof adminDb>>, icePeriod: string, dimension: IceMarketDimension,
): Promise<{ rows: MarketSliceRow[]; total: number }> {
  const window = resolveMarketWindow(icePeriod, "month");
  const rows = (await getIceMarketSlice({ dimension, window, limit: 500 })) as MarketSliceRow[];
  return { rows, total: rows.reduce((sum, row) => sum + Number(row.registrations || 0), 0) };
}

export async function getPublicMarketIce(dimension: IcePublicDimension = "brand"): Promise<PublicMarket | null> {
  if (!isIcePublicDimension(dimension)) throw new IceMarketDimensionError(dimension);
  const db = adminDb();
  if (!db) return null;

  // §14.1/§14.3: Ice's period is a Buddhist "YYYY-MM" string, never a SQL
  // date -- kept as-delivered rather than converted to a fake Gregorian
  // "YYYY-MM-01", unlike the legacy PublicMarket.period. This is a
  // deliberate, documented visible difference (see the M4 PR report), not
  // an accident: converting it would misrepresent the calendar Ice uses.
  const period = await latestIcePeriod(db);
  if (!period) return null;
  const previousPeriod = shortIcePeriod(shiftReportPeriod(period, -1));

  const [current, previous] = await Promise.all([
    icePeriodTotal(db, period, dimension),
    icePeriodTotal(db, previousPeriod, dimension).catch(() => ({ rows: [] as MarketSliceRow[], total: 0 })),
  ]);

  const months: string[] = [];
  for (let back = PUBLIC_TREND_MONTHS - 1; back >= 0; back -= 1) {
    months.push(shortIcePeriod(shiftReportPeriod(period, -back)));
  }
  const totals = await Promise.all(months.map(async (month) => {
    if (month === period) return current.total;
    if (month === previousPeriod) return previous.total || null;
    try {
      const slice = await icePeriodTotal(db, month, dimension);
      return slice.total || null;
    } catch {
      return null;
    }
  }));

  return assemblePublicMarket({
    dimension,
    period,
    previousPeriod,
    currentRows: current.rows,
    currentTotal: current.total,
    previousRows: previous.rows,
    brandLimit: PUBLIC_BRAND_LIMIT,
    trend: months.map((month, index) => ({ period: month, total: totals[index] ?? null })),
  });
}
