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
  assertIceFiltersSupported,
  distinctSortedPeriods,
  fetchAllPages,
  findPanelRelease,
  iceAccessAllows,
  isIceMarketDimension,
  resolveWheelTyreAvailability,
  sliceIceByBodyType,
  sliceIceByBrand,
  sliceIceByModel,
  sliceIceByPowertrain,
  sliceIceByRegistrationType,
  sliceIceBySegment,
  type IceCrosswalkLink,
  type IceMarketDimension,
  type IceMarketFilters,
  type IceModelGroupRedirectRow,
  type IceModelSliceRow,
  type IcePanelAccess,
  type IcePanelRelease,
  type IcePowertrainSliceRow,
  type IceRegPowertrainRow,
  type IceRegProvinceRow,
  type IceRegTrendRow,
  type IceRimProvinceRow,
  type IceTyreCoverageRow,
  type IceTyreProvinceRow,
  type VehicleModelDim,
  type WheelTyreAvailability,
} from "@/lib/ice-market-engine";

export { isIceMarketDimension, findPanelRelease, iceAccessAllows };
export type { IceMarketDimension, IcePanelAccess, IcePanelRelease, WheelTyreAvailability };

type Db = ReturnType<typeof adminDb>;

const PAGE_SIZE = 1000;

/** PR #189 review round 2, fix 3: raised from an arbitrary 100,000.
 * ice_reg_trend is the finest-grain panel this engine reads (period x
 * province x reg_type x brand x model_group_id). Thailand has ~77 provinces,
 * DLT registration types in the low single digits in practice, and Ice's own
 * brand/model_group_id universes are in the hundreds, not thousands --
 * 77 x 10 x 200 x 500 x 12 months (a full rolling12 window) is ~924,000,000
 * as a theoretical combinatorial ceiling, but Ice does not emit zero-row
 * combinations, so a real window is orders of magnitude sparser than that.
 * This ceiling is set two orders of magnitude above any plausible real
 * rolling12/ytd row count at that grain -- not tuned to today's synthetic
 * fixture -- so a window that genuinely needs more than this is a real
 * operational event that must be reported loudly (PaginationLimitExceededError
 * from lib/ice-market-engine.ts), never silently truncated. */
const MAX_ROWS = 2_000_000;

/** Every per-panel fetch orders by the table's FULL primary-key column list
 * (migration_v62's own PKs), never by `period` alone -- `period` is not
 * unique, so an ORDER BY on it alone gives Postgres no guaranteed stable
 * tie-break across repeated reads, which makes offset/range pagination
 * non-deterministic (a row can be skipped or duplicated across pages). */
async function pagedSelect<T>(
  db: NonNullable<Db>, table: string, columns: string, orderColumns: readonly string[], window: MarketPeriodWindow,
): Promise<T[]> {
  return fetchAllPages<T>(
    async (offset, limit) => {
      let query = db.from(table).select(columns).gte("period", window.from).lte("period", window.to);
      for (const column of orderColumns) query = query.order(column, { ascending: true });
      const { data, error } = await query.range(offset, offset + limit - 1);
      if (error) throw new Error(`${table} query failed: ${error.message}`);
      return (data ?? []) as T[];
    },
    PAGE_SIZE, MAX_ROWS,
  );
}

/** Same determinism rule as pagedSelect, for a full-table (unwindowed) fetch. */
async function pagedSelectAll<T>(
  db: NonNullable<Db>, table: string, columns: string, orderColumns: readonly string[],
): Promise<T[]> {
  return fetchAllPages<T>(
    async (offset, limit) => {
      let query = db.from(table).select(columns);
      for (const column of orderColumns) query = query.order(column, { ascending: true });
      const { data, error } = await query.range(offset, offset + limit - 1);
      if (error) throw new Error(`${table} query failed: ${error.message}`);
      return (data ?? []) as T[];
    },
    PAGE_SIZE, MAX_ROWS,
  );
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
// Per-panel fetchers -- column lists and ordering match migration_v62 +
// migration_v64's primary keys exactly. reg_powertrain's order includes
// certainty and tyre_province's includes rim_inch (migration_v64, R5
// compatibility fix for the real TDR_FULL_2569-09_v3_M7.0.zip contract) --
// without them, two rows sharing every other PK column (e.g. the same
// model_group_id/fuel_group at certainty=exact and certainty=range) have no
// deterministic tie-break between them, which is exactly the pagedSelect
// doc comment's non-determinism risk above, not merely a theoretical one.
// ---------------------------------------------------------------------------

export async function fetchIceRegProvince(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRegProvinceRow[]> {
  return pagedSelect<IceRegProvinceRow>(
    db, "ice_reg_province", "period,province,reg_type,brand,fuel_group,reg_count",
    ["period", "province", "reg_type", "brand", "fuel_group"], iceWindow(window));
}

export async function fetchIceRegTrend(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRegTrendRow[]> {
  return pagedSelect<IceRegTrendRow>(
    db, "ice_reg_trend", "period,province,reg_type,brand,model_group_id,model_name,reg_count",
    ["period", "province", "reg_type", "brand", "model_group_id"], iceWindow(window));
}

export async function fetchIceRegPowertrain(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRegPowertrainRow[]> {
  return pagedSelect<IceRegPowertrainRow>(
    db, "ice_reg_powertrain",
    "period,province,reg_type,brand,model_group_id,model_name,fuel_group,reg_est,reg_min,reg_max,certainty",
    ["period", "province", "reg_type", "brand", "model_group_id", "fuel_group", "certainty"], iceWindow(window));
}

export async function fetchIceRimProvince(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceRimProvinceRow[]> {
  return pagedSelect<IceRimProvinceRow>(
    db, "ice_rim_province", "period,province,reg_type,brand,rim_bucket,reg_est",
    ["period", "province", "reg_type", "brand", "rim_bucket"], iceWindow(window));
}

export async function fetchIceTyreProvince(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceTyreProvinceRow[]> {
  return pagedSelect<IceTyreProvinceRow>(
    db, "ice_tyre_province", "period,province,reg_type,brand,tyre_size,rim_inch,reg_est",
    ["period", "province", "reg_type", "brand", "tyre_size", "rim_inch"], iceWindow(window));
}

export async function fetchIceTyreCoverage(db: NonNullable<Db>, window: MarketPeriodWindow): Promise<IceTyreCoverageRow[]> {
  return pagedSelect<IceTyreCoverageRow>(
    db, "ice_tyre_coverage", "period,province,reg_type,brand,reg_total,reg_tyre_known",
    ["period", "province", "reg_type", "brand"], iceWindow(window));
}

export async function fetchIceCrosswalk(db: NonNullable<Db>): Promise<IceCrosswalkLink[]> {
  return pagedSelectAll<IceCrosswalkLink>(db, "ice_model_crosswalk", "model_group_id,canonical_model_id,status", ["id"]);
}

export async function fetchIceModelGroupRedirects(db: NonNullable<Db>): Promise<IceModelGroupRedirectRow[]> {
  return pagedSelectAll<IceModelGroupRedirectRow>(
    db, "ice_model_group_redirects", "old_model_group_id,new_model_group_id", ["old_model_group_id"]);
}

/** vehicle_models' segment/body_type, read only for the crosswalk-derived
 * dimensions §14.3 explicitly requires a TDR link for. Never writes, never
 * used to regroup a non-TDR dimension. */
export async function fetchVehicleModelDims(db: NonNullable<Db>): Promise<VehicleModelDim[]> {
  return pagedSelectAll<VehicleModelDim>(db, "vehicle_models", "canonical_id,segment,body_type", ["canonical_id"]);
}

/** The latest accepted import's release identity -- period, master_version
 * and the full per-panel metadata array, per ice_package_imports (M2's
 * append-only log of each accepted replace; R1/M2.1 persists period_from/
 * period_to/access/free_scope/confirmed_by per panel in the `panels` jsonb
 * column). This is the authoritative release source (ROADMAP R3 item 4):
 * period/master_version/panel metadata are read from this one row, never
 * inferred by scanning fact rows. `panels` is returned raw (validated lazily,
 * per panel, by findPanelRelease) since not every caller needs every panel's
 * metadata. Returns null only when no import has ever been accepted yet --
 * a real, legitimate "no data" state, not a malformed-metadata refusal. */
export type IceImportRelease = { period: string; master_version: string; panels: unknown };

export async function latestIceImportRelease(db: NonNullable<Db>): Promise<IceImportRelease | null> {
  const { data, error } = await db
    .from("ice_package_imports")
    .select("period,master_version,panels")
    .order("imported_at", { ascending: false })
    .limit(1);
  if (error) throw new Error(`ice_package_imports query failed: ${error.message}`);
  if (!data?.length) return null;
  const row = data[0] as { period: unknown; master_version: unknown; panels: unknown };
  return { period: String(row.period), master_version: String(row.master_version), panels: row.panels };
}

/** The latest accepted import's period alone -- kept for callers (e.g.
 * lib/ice-public-market.ts) that only need "what release are we currently
 * showing", not the full panel metadata. */
export async function latestIcePeriod(db: NonNullable<Db>): Promise<string | null> {
  const release = await latestIceImportRelease(db);
  return release ? release.period : null;
}

/** One panel's persisted release metadata from the latest accepted import
 * (ROADMAP R3 items 1-3: real period_from/access/free_scope, never
 * hard-coded or defaulted). null when no import exists yet; throws
 * IcePanelMetadataError (via findPanelRelease) when an import exists but
 * this panel's metadata is missing or malformed -- never guessed. */
export async function latestIcePanelRelease(db: NonNullable<Db>, panelId: string): Promise<IcePanelRelease | null> {
  const release = await latestIceImportRelease(db);
  if (!release) return null;
  return findPanelRelease(release.panels, panelId);
}

/** Wheel/tyre availability against the real persisted period_from of the
 * named panel. rim_province and tyre_province persist their own period_from
 * independently and may differ, so each call reads its own panel's entry --
 * never a value shared between them, never hard-coded. null when no import
 * exists yet; throws when the import exists but this panel's period_from is
 * missing/malformed. */
export async function iceWheelTyreAvailability(
  db: NonNullable<Db>, panelId: "rim_province" | "tyre_province", period: string,
): Promise<WheelTyreAvailability | null> {
  const release = await latestIcePanelRelease(db, panelId);
  if (!release) return null;
  return resolveWheelTyreAvailability(release.period_from, period);
}

// ---------------------------------------------------------------------------
// Dimension-routing slice: picks the correct single panel per §14.3's source
// rule and returns the contract-shaped MarketSliceRow[] (or IceModelSliceRow[]/
// IcePowertrainSliceRow[], a MarketSliceRow plus optional metadata fields --
// §15.2's "new metadata may only be optional additions"). Validates the
// requested filters against the chosen dimension's actual source panel
// before doing any fetch (PR #189 review round 2, fix 4) -- an unsupported
// filter throws rather than being silently dropped.
// ---------------------------------------------------------------------------

export async function getIceMarketSlice(args: {
  dimension: IceMarketDimension;
  window: MarketPeriodWindow;
  filters?: IceMarketFilters;
  limit?: number;
}): Promise<MarketSliceRow[] | IceModelSliceRow[] | IcePowertrainSliceRow[]> {
  const filters = args.filters ?? {};
  assertIceFiltersSupported(args.dimension, filters);
  const db = adminDb();
  if (!db) return [];
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
    default: {
      const exhaustive: never = args.dimension;
      throw new Error(`unreachable Ice market dimension: ${String(exhaustive)}`);
    }
  }
}

export class IceMarketDimensionError extends Error {
  constructor(dimension: string) {
    super(
      `"${dimension}" has no defined Ice/TDR source in VEHICLE_DB_V3.md §14.3 -- `
      + "the M4 engine refuses to guess at it rather than silently reusing legacy "
      + "registration data or Vehicle Master payload fields. See the M4 PR's ambiguity report.",
    );
  }
}

export type IceMarketReport = {
  dimension: IceMarketDimension;
  window: MarketPeriodWindow;
  rows: MarketSliceRow[] | IceModelSliceRow[] | IcePowertrainSliceRow[];
  comparison: {
    window: MarketPeriodWindow;
    rows: MarketSliceRow[] | IceModelSliceRow[] | IcePowertrainSliceRow[];
    movement: MarketMovementRow[];
  } | null;
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
  if (!isIceMarketDimension(args.dimension)) throw new IceMarketDimensionError(args.dimension);
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

/** Which periods actually have live data -- PR #189 review round 2, fix 2:
 * this used to read ice_package_imports.period (one row per accepted
 * *release event*, not per historical period a replace-whole-set payload
 * contains). A single Full Package import can carry many historical periods
 * under one release's headline period, so that was undercounting real
 * coverage. This instead pages ice_reg_province's own `period` column --
 * safe to read post-commit because migration_v62's ice_commit_staged_import
 * is one atomic transaction, so a committed row is never a partial-replace
 * artifact -- and deduplicates/sorts with the pure distinctSortedPeriods
 * (lib/ice-market-engine.ts). ice_reg_province is the base registration-count
 * panel every accepted import carries, so its period coverage is the
 * ground truth for "what periods does live Ice data actually span" (and
 * M2's own post-import check already requires reg_province and reg_trend to
 * agree on totals per period, so they necessarily agree on period coverage
 * too). A server-side DISTINCT RPC was considered and rejected for this fix:
 * reg_province's per-period row count (brand x fuel_group x province x
 * reg_type) is bounded and small enough that paging the one `period` column
 * and deduplicating client-side is simple, correct, and needs no new
 * migration -- revisit with an RPC only if real volume proves otherwise. */
export async function iceAvailablePeriods(db: NonNullable<Db>): Promise<string[]> {
  const rows = await pagedSelectAll<{ period: string }>(
    db, "ice_reg_province", "period", ["period", "province", "reg_type", "brand", "fuel_group"]);
  return distinctSortedPeriods(rows.map((row) => toWindowPeriod(row.period)));
}

export function missingIceReportPeriods(window: MarketPeriodWindow, available: Iterable<string>): string[] {
  return missingReportPeriods(window, available);
}

export { reportPeriods };
