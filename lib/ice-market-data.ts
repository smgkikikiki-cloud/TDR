/**
 * Market Track M4 -- the I/O layer for the Ice-backed market engine.
 *
 * Reads only the Ice panel tables (migration_v62), the Ice crosswalk
 * (migration_v63) and vehicle_models/vehicle_brands (migration_v57, read-only,
 * for the segment/body_type/model link -- §14.3 permits a TDR dimension only
 * where the contract explicitly requires one). Never reads
 * registration_reporting_source or any other legacy registration table --
 * the legacy engine must not be a source for this engine's output.
 *
 * Every Ice table here is service-role-only (no anon/authenticated grant), so
 * every function in this file runs on the server with `adminDb()`, exactly
 * like `lib/registration-analytics.ts`/`lib/public-market.ts`.
 *
 * This module is NOT wired into any live page or API route in M4 -- see
 * docs/WORK_STATE.md and the M4 PR description. It exists so the engine can be
 * proven against real Supabase access ahead of the M5 cutover.
 */
import { adminDb } from "@/lib/supabase";
import {
  compareMarketSliceRows,
  missingReportPeriods,
  normalizeReportPeriod,
  reportPeriods,
  resolveMarketWindow,
  type MarketMovementRow,
  type MarketPeriodWindow,
  type MarketSliceRow,
  type MarketWindow,
} from "@/lib/registration-market";
import {
  sliceIceByBodyType,
  sliceIceByBrand,
  sliceIceByModel,
  sliceIceByPowertrain,
  sliceIceByRegistrationType,
  sliceIceBySegment,
  type IceCrosswalkLink,
  type IceMarketFilters,
  type IceModelGroupRedirectRow,
  type IceModelSliceRow,
  type IceRegPowertrainRow,
  type IceRegProvinceRow,
  type IceRegTrendRow,
  type IceRimProvinceRow,
  type IceTyreCoverageRow,
  type IceTyreProvinceRow,
  type VehicleModelDim,
} from "@/lib/ice-market-engine";

type Db = ReturnType<typeof adminDb>;

const PAGE_SIZE = 1000;
const MAX_ROWS = 100000;

/** The six dimensions §14.3 gives an explicit Ice/TDR source rule for.
 * oem_group, market_position, import_type, origin_country, brand_origin and
 * market_scope are deliberately absent: §14.3 does not define their Ice/TDR
 * sourcing, so this engine never guesses at them (see docs/WORK_STATE.md's
 * "unresolved dimension ambiguities" list and §14.3 of the M4 PR report). */
export type IceMarketDimension = "brand" | "model" | "segment" | "body_type" | "powertrain" | "registration_type";

export class IceMarketDimensionError extends Error {
  constructor(dimension: string) {
    super(
      `"${dimension}" has no defined Ice/TDR source in VEHICLE_DB_V3.md §14.3 -- `
      + "the M4 engine refuses to guess at it rather than silently reusing legacy "
      + "registration data or Vehicle Master payload fields. See the M4 PR's ambiguity report.",
    );
  }
}

export function isIceMarketDimension(value: string): value is IceMarketDimension {
  return value === "brand" || value === "model" || value === "segment"
    || value === "body_type" || value === "powertrain" || value === "registration_type";
}

async function pagedSelect<T>(
  db: NonNullable<Db>, table: string, columns: string, window: MarketPeriodWindow,
): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; offset < MAX_ROWS; offset += PAGE_SIZE) {
    const { data, error } = await db
      .from(table)
      .select(columns)
      .gte("period", window.from)
      .lte("period", window.to)
      .order("period", { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1);
    if (error) throw new Error(`${table} query failed: ${error.message}`);
    const page = (data ?? []) as T[];
    rows.push(...page);
    if (page.length < PAGE_SIZE) return rows;
  }
  throw new Error(`${table} window exceeds ${MAX_ROWS.toLocaleString()} rows`);
}

// ---------------------------------------------------------------------------
// Period normalization -- Ice stores "YYYY-MM" (migration_v62's check
// constraint), not the legacy "YYYY-MM-DD". The window helpers imported above
// do pure year*12+month integer arithmetic on the string's digits and never
// construct a real calendar Date, so they are correct unchanged on Ice's
// Buddhist year numbers -- but they expect/return a "YYYY-MM-DD"-shaped
// string, so this module normalizes at its own boundary (append/strip "-01")
// rather than changing those shared helpers.
// ---------------------------------------------------------------------------

function toIcePeriod(normalized: string): string {
  return normalized.slice(0, 7);
}

function toWindowPeriod(icePeriod: string): string {
  const normalized = normalizeReportPeriod(icePeriod);
  if (!normalized) throw new Error(`invalid Ice period: ${icePeriod}`);
  return normalized;
}

function iceWindow(window: MarketPeriodWindow): MarketPeriodWindow {
  return { from: toIcePeriod(window.from), to: toIcePeriod(window.to) };
}

// ---------------------------------------------------------------------------
// Per-panel fetchers
// ---------------------------------------------------------------------------

export async function fetchIceRegProvince(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRegProvinceRow[]> {
  return pagedSelect<IceRegProvinceRow>(
    db, "ice_reg_province", "period,province,reg_type,brand,fuel_group,reg_count", iceWindow(window));
}

export async function fetchIceRegTrend(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRegTrendRow[]> {
  return pagedSelect<IceRegTrendRow>(
    db, "ice_reg_trend", "period,province,reg_type,brand,model_group_id,model_name,reg_count", iceWindow(window));
}

export async function fetchIceRegPowertrain(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRegPowertrainRow[]> {
  return pagedSelect<IceRegPowertrainRow>(
    db, "ice_reg_powertrain",
    "period,province,reg_type,brand,model_group_id,model_name,fuel_group,reg_est,reg_min,reg_max,certainty",
    iceWindow(window));
}

export async function fetchIceRimProvince(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRimProvinceRow[]> {
  return pagedSelect<IceRimProvinceRow>(
    db, "ice_rim_province", "period,province,reg_type,brand,rim_bucket,reg_est", iceWindow(window));
}

export async function fetchIceTyreProvince(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceTyreProvinceRow[]> {
  return pagedSelect<IceTyreProvinceRow>(
    db, "ice_tyre_province", "period,province,reg_type,brand,tyre_size,rim_inch,reg_est", iceWindow(window));
}

export async function fetchIceTyreCoverage(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceTyreCoverageRow[]> {
  return pagedSelect<IceTyreCoverageRow>(
    db, "ice_tyre_coverage", "period,province,reg_type,brand,reg_total,reg_tyre_known", iceWindow(window));
}

export async function fetchIceCrosswalk(db: NonNullable<Db>): Promise<IceCrosswalkLink[]> {
  const rows: IceCrosswalkLink[] = [];
  for (let offset = 0; offset < MAX_ROWS; offset += PAGE_SIZE) {
    const { data, error } = await db
      .from("ice_model_crosswalk")
      .select("model_group_id,canonical_model_id,status")
      .range(offset, offset + PAGE_SIZE - 1);
    if (error) throw new Error(`ice_model_crosswalk query failed: ${error.message}`);
    const page = (data ?? []) as IceCrosswalkLink[];
    rows.push(...page);
    if (page.length < PAGE_SIZE) return rows;
  }
  throw new Error(`ice_model_crosswalk exceeds ${MAX_ROWS.toLocaleString()} rows`);
}

export async function fetchIceModelGroupRedirects(db: NonNullable<Db>): Promise<IceModelGroupRedirectRow[]> {
  const { data, error } = await db.from("ice_model_group_redirects").select("old_model_group_id,new_model_group_id");
  if (error) throw new Error(`ice_model_group_redirects query failed: ${error.message}`);
  return (data ?? []) as IceModelGroupRedirectRow[];
}

/** vehicle_models' segment/body_type, read only for the crosswalk-derived
 * dimensions §14.3 explicitly requires a TDR link for. Never writes, never
 * used to regroup a non-TDR dimension. */
export async function fetchVehicleModelDims(db: NonNullable<Db>): Promise<VehicleModelDim[]> {
  const rows: VehicleModelDim[] = [];
  for (let offset = 0; offset < MAX_ROWS; offset += PAGE_SIZE) {
    const { data, error } = await db
      .from("vehicle_models")
      .select("canonical_id,segment,body_type")
      .range(offset, offset + PAGE_SIZE - 1);
    if (error) throw new Error(`vehicle_models query failed: ${error.message}`);
    const page = (data ?? []) as VehicleModelDim[];
    rows.push(...page);
    if (page.length < PAGE_SIZE) return rows;
  }
  throw new Error(`vehicle_models exceeds ${MAX_ROWS.toLocaleString()} rows`);
}

/** The latest accepted import's period, per ice_package_imports (M2's
 * append-only log of each accepted replace) -- the authoritative answer to
 * "what period does the live ice_* data represent", not a MAX(period) scan
 * of a fact table, which could pick up a mid-replace partial state. */
export async function latestIcePeriod(db: NonNullable<Db>): Promise<string | null> {
  const { data, error } = await db
    .from("ice_package_imports")
    .select("period")
    .order("imported_at", { ascending: false })
    .limit(1);
  if (error) throw new Error(`ice_package_imports query failed: ${error.message}`);
  return data?.length ? String(data[0].period) : null;
}

// ---------------------------------------------------------------------------
// Dimension-routing slice: picks the correct single panel per §14.3's source
// rule and returns the contract-shaped MarketSliceRow[] (or IceModelSliceRow[]
// for "model", which is a MarketSliceRow plus the optional canonical_model_id
// link -- §15.2's "new metadata may only be optional additions").
// ---------------------------------------------------------------------------

export async function getIceMarketSlice(args: {
  dimension: IceMarketDimension;
  window: MarketPeriodWindow;
  filters?: IceMarketFilters;
  limit?: number;
}): Promise<MarketSliceRow[] | IceModelSliceRow[]> {
  const db = adminDb();
  if (!db) return [];
  const filters = args.filters ?? {};
  const limit = args.limit ?? 100;

  switch (args.dimension) {
    case "brand":
      return sliceIceByBrand(await fetchIceRegProvince(db, args.window), filters, limit);
    case "registration_type":
      return sliceIceByRegistrationType(await fetchIceRegProvince(db, args.window), filters, limit);
    case "powertrain":
      return sliceIceByPowertrain(await fetchIceRegPowertrain(db, args.window), filters, limit);
    case "model": {
      const [trend, crosswalk] = await Promise.all([fetchIceRegTrend(db, args.window), fetchIceCrosswalk(db)]);
      return sliceIceByModel(trend, crosswalk, filters, limit);
    }
    case "segment": {
      const [trend, crosswalk, models] = await Promise.all([
        fetchIceRegTrend(db, args.window), fetchIceCrosswalk(db), fetchVehicleModelDims(db),
      ]);
      return sliceIceBySegment(trend, crosswalk, models, filters, limit);
    }
    case "body_type": {
      const [trend, crosswalk, models] = await Promise.all([
        fetchIceRegTrend(db, args.window), fetchIceCrosswalk(db), fetchVehicleModelDims(db),
      ]);
      return sliceIceByBodyType(trend, crosswalk, models, filters, limit);
    }
    default:
      throw new IceMarketDimensionError(args.dimension);
  }
}

export type IceMarketReport = {
  dimension: IceMarketDimension;
  window: MarketPeriodWindow;
  rows: MarketSliceRow[] | IceModelSliceRow[];
  comparison: { window: MarketPeriodWindow; rows: MarketSliceRow[] | IceModelSliceRow[]; movement: MarketMovementRow[] } | null;
};

/** The "member market engine" entry point (M4 §7): current window, optional
 * comparison window, dimension slice, filters -- the Ice equivalent of
 * `getRegistrationMarketSlice`, minus the tier/quota/access-policy plumbing
 * (orthogonal to the data source and unchanged in the live route; M5 wires
 * this function in behind that existing gate, not before). */
export async function getIceMarketReport(args: {
  dimension: IceMarketDimension;
  period: string;
  window: MarketWindow;
  comparisonWindow?: MarketPeriodWindow | null;
  filters?: IceMarketFilters;
  limit?: number;
}): Promise<IceMarketReport> {
  const window = resolveMarketWindow(args.period, args.window);
  const rows = await getIceMarketSlice({ dimension: args.dimension, window, filters: args.filters, limit: args.limit });

  let comparison: IceMarketReport["comparison"] = null;
  if (args.comparisonWindow) {
    const comparisonRows = await getIceMarketSlice({
      dimension: args.dimension, window: args.comparisonWindow, filters: args.filters, limit: args.limit,
    });
    comparison = {
      window: args.comparisonWindow,
      rows: comparisonRows,
      movement: compareMarketSliceRows(comparisonRows as MarketSliceRow[], rows as MarketSliceRow[]),
    };
  }

  return { dimension: args.dimension, window, rows, comparison };
}

/** Which periods in a window actually have an accepted Ice import -- the Ice
 * equivalent of `missingReportPeriods`/`getRegistrationAvailablePeriods`,
 * sourced from ice_package_imports rather than registration_analytics_coverage. */
export async function iceAvailablePeriods(db: NonNullable<Db>): Promise<string[]> {
  const { data, error } = await db.from("ice_package_imports").select("period").order("period", { ascending: true });
  if (error) throw new Error(`ice_package_imports query failed: ${error.message}`);
  return [...new Set((data ?? []).map((row: { period: string }) => toWindowPeriod(row.period)))];
}

export function missingIceReportPeriods(window: MarketPeriodWindow, available: Iterable<string>): string[] {
  return missingReportPeriods(window, available);
}

export { reportPeriods };
