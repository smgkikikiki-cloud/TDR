/**
 * The public market view: one month of registrations, at brand grain.
 *
 * Registration data is the paid layer, and none of it is readable with the
 * browser's own key -- every one of its tables answers `anon` with 401. This
 * module is the single deliberate opening in that wall: it runs on the server
 * with the service-role credential and publishes an aggregate that is
 * intentionally shallow.
 *
 * What makes it shallow is the point, so it is stated rather than implied:
 *
 *   * brand grain only -- never a model, a trim or a segment cut;
 *   * the latest published month and the one before it, never a chosen window;
 *   * the top brands and one "others" bucket, never the full ranking;
 *   * totals for the trend line, never a per-brand series;
 *   * no export, no filters, no period picker.
 *
 * Everything a subscriber pays for -- choosing the window, the dimension and
 * the filters, reading it per model, going back further than a year, taking it
 * away as a file -- stays where it was. This is the shop window, not the shop.
 */
import { adminDb } from "@/lib/supabase";
import {
  canonicalizeRegistrationRows,
  fetchRegistrationRows,
} from "@/lib/registration-analytics";
import {
  compareMarketSliceRows,
  resolveMarketWindow,
  shiftReportPeriod,
  sliceMarketFacts,
  type MarketDimension,
  type MarketSliceRow,
} from "@/lib/registration-market";

/** The cuts a public reader may take.
 *
 *  The engine ranks twelve dimensions. These six are the ones that describe
 *  the shape of the market rather than the performance of a product: what is
 *  selling as a category, not which car. `model` is deliberately absent, and
 *  so are the filters -- a reader here changes what the market is cut BY,
 *  never which slice of it they are looking at. That distinction is the whole
 *  boundary: the shape is published, the interrogation is sold.
 */
export const PUBLIC_DIMENSIONS = [
  { value: "brand", label: "แบรนด์" },
  { value: "powertrain", label: "ระบบขับเคลื่อน" },
  { value: "body_type", label: "ประเภทตัวถัง" },
  { value: "segment", label: "Segment" },
  { value: "origin_country", label: "ประเทศที่ผลิต" },
  { value: "oem_group", label: "กลุ่มผู้ผลิต" },
] as const satisfies readonly { value: MarketDimension; label: string }[];

export type PublicDimension = (typeof PUBLIC_DIMENSIONS)[number]["value"];

export function isPublicDimension(value: string | null | undefined): value is PublicDimension {
  return PUBLIC_DIMENSIONS.some((item) => item.value === value);
}

/** How many entries are named before the rest become one slice. Eight is the
 *  categorical palette's length: a ninth hue would have to be invented, and an
 *  invented hue is how a chart stops being readable. */
export const PUBLIC_BRAND_LIMIT = 8;

/** How far the public trend line reaches back. */
export const PUBLIC_TREND_MONTHS = 12;

export type PublicMarketMover = { key: string; label: string; delta: number; sharePct: number };

export type PublicMarket = {
  dimension: PublicDimension;
  period: string;
  previousPeriod: string | null;
  totalRegistrations: number;
  /** Share for the latest month, largest first, with the tail folded in. */
  brands: { key: string; label: string; registrations: number; sharePct: number }[];
  others: { registrations: number; sharePct: number } | null;
  /** Month-on-month change in units, biggest movement either way first. */
  movers: PublicMarketMover[];
  /** Total registrations per month, oldest first. A month with no published
   *  data is null rather than zero: nobody registered nothing. */
  trend: { period: string; total: number | null }[];
};

async function periodTotal(db: any, period: string, dimension: PublicDimension,
): Promise<{ rows: MarketSliceRow[]; total: number }> {
  const window = resolveMarketWindow(period, "month");
  // No registration-type filter is ever applied here, and registration_type is
  // not a public cut, so the "keep it open" flag has nothing to keep open.
  const raw = await fetchRegistrationRows(db, window, undefined, false);
  const facts = await canonicalizeRegistrationRows(db, raw, false);
  const rows = sliceMarketFacts({ facts, dimension, limit: 500 });
  return { rows, total: rows.reduce((sum, row) => sum + Number(row.registrations || 0), 0) };
}

/** The latest month the reporting source actually carries. */
async function latestPublishedPeriod(db: any): Promise<string | null> {
  const { data, error } = await db
    .from("registration_reporting_source")
    .select("period")
    .order("period", { ascending: false })
    .limit(1);
  if (error || !data?.length) return null;
  return String(data[0].period);
}

export async function getPublicMarket(dimension: PublicDimension = "brand"): Promise<PublicMarket | null> {
  const db = adminDb();
  if (!db) return null;

  const period = await latestPublishedPeriod(db);
  if (!period) return null;
  const previousPeriod = shiftReportPeriod(period, -1);

  const [current, previous] = await Promise.all([
    periodTotal(db, period, dimension),
    periodTotal(db, previousPeriod, dimension).catch(() => ({ rows: [] as MarketSliceRow[], total: 0 })),
  ]);

  const named = current.rows.slice(0, PUBLIC_BRAND_LIMIT).map((row) => ({
    key: row.entity_key,
    label: row.entity_label,
    registrations: Number(row.registrations || 0),
    sharePct: Number(row.market_share_pct || 0),
  }));
  const tail = current.rows.slice(PUBLIC_BRAND_LIMIT);
  const tailUnits = tail.reduce((sum, row) => sum + Number(row.registrations || 0), 0);
  const others = tail.length
    ? { registrations: tailUnits, sharePct: current.total ? Math.round((10000 * tailUnits) / current.total) / 100 : 0 }
    : null;

  // Movement is computed over the full ranking and only then cut down, so a
  // brand that climbed out of the tail is not invisible.
  const movers = compareMarketSliceRows(previous.rows, current.rows)
    .map((row) => ({
      key: row.entity_key,
      label: row.entity_label,
      delta: row.units_change,
      sharePct: row.share_current_pct,
    }))
    .filter((row) => row.delta !== 0)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 10)
    .sort((a, b) => b.delta - a.delta);

  const months: string[] = [];
  for (let back = PUBLIC_TREND_MONTHS - 1; back >= 0; back -= 1) {
    months.push(shiftReportPeriod(period, -back));
  }
  const totals = await Promise.all(months.map(async (month) => {
    if (month === period) return current.total;
    if (month === previousPeriod) return previous.total || null;
    try {
      const slice = await periodTotal(db, month, dimension);
      return slice.total || null;
    } catch {
      return null;
    }
  }));

  return {
    dimension,
    period,
    previousPeriod,
    totalRegistrations: current.total,
    brands: named,
    others,
    movers,
    trend: months.map((month, index) => ({ period: month, total: totals[index] ?? null })),
  };
}
