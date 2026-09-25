import { getActiveHistoricalModelState, resolveHistoricalModelState } from "@/lib/historical-model-state";
import {
  sliceMarketFacts,
  type CanonicalRegistrationFact,
  type MarketDimension,
  type MarketPeriodWindow,
  type MarketSliceFilters,
  type MarketSliceRow,
} from "@/lib/registration-market";
import { requireMemberAccess, requireUsage, getSalesModuleSelection, AccessPolicyError, type AccessContext } from "@/lib/access-policy-server";
import {
  currentSalesModuleCycleKey,
  historyWindowStart,
  areMarketFiltersAllowed,
  isMarketDimensionAllowed,
  isRegistrationDimensionAllowed,
  type SalesModule,
} from "@/lib/access-policy";

export {
  compareMarketSliceRows,
  comparisonMarketWindow,
  isMarketComparison,
  isMarketDimension,
  isMarketWindow,
  missingReportPeriods,
  normalizeReportPeriod,
  previousMarketWindow,
  reportPeriods,
  resolveMarketWindow,
  shiftReportPeriod,
  sliceMarketFacts,
} from "@/lib/registration-market";
export type {
  CanonicalRegistrationFact,
  MarketComparison,
  MarketDimension,
  MarketMovementRow,
  MarketPeriodWindow,
  MarketSliceFilters,
  MarketSliceRow,
  MarketWindow,
} from "@/lib/registration-market";
export type { AccessContext } from "@/lib/access-policy-server";

export type RegistrationDimension =
  | "coverage"
  | "brand"
  | "model"
  | "mom"
  | "segment"
  | "powertrain"
  | "chinese-bev";

const ALL_REGISTRATION_DIMENSIONS: RegistrationDimension[] = [
  "brand", "model", "mom", "segment", "powertrain", "chinese-bev",
];

type JsonObject = Record<string, unknown>;

type CanonicalModelRow = {
  canonical_id: string | null;
  tdr_model_id: string | null;
  brand_id: string | null;
  name_en: string | null;
  name_th: string | null;
  segment: string | null;
  body_type: string | null;
  payload: JsonObject | null;
};

type CanonicalBrandRow = {
  canonical_id: string | null;
  tdr_brand_id: string | null;
  slug: string | null;
  name_en: string | null;
  name_th: string | null;
  payload: JsonObject | null;
};

type RegistrationBrandAliasRow = {
  raw_brand_norm: string;
  brand_id: string;
};

const PAGE_SIZE = 1000;
const MAX_FACT_ROWS = 50000;

const VIEW_CONFIG: Record<RegistrationDimension, { table: string; order: string; ascending?: boolean }> = {
  coverage: { table: "registration_analytics_coverage", order: "period", ascending: true },
  brand: { table: "registration_brand_share", order: "market_rank", ascending: true },
  model: { table: "registration_model_share", order: "market_rank", ascending: true },
  mom: { table: "registration_model_mom", order: "mom_delta", ascending: false },
  segment: { table: "registration_monthly_segment", order: "segment_rank", ascending: true },
  powertrain: { table: "registration_monthly_powertrain", order: "powertrain_rank", ascending: true },
  "chinese-bev": { table: "registration_chinese_bev_rank", order: "bev_rank", ascending: true },
};

export class RegistrationAccessError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function isRegistrationDimension(value: string | null): value is RegistrationDimension {
  return Boolean(value && value in VIEW_CONFIG);
}

// A signed-in, ACTIVATED TDR account -- Free included -- may reach
// registration analytics; access used to be gated by a binary
// `registration_full` entitlement, but under the tiered model every
// activated account gets Sales Tools, just at different quotas/module/
// history scope. Legacy registration_full/registration_monthly
// subscribers still resolve to PRO via resolveTierFromEntitlements, and
// are grandfathered by migration_v34, so their access is unchanged.
// Signing in is the entitlement: tier and quota decide what comes back,
// and an unverified phone or a half-filled profile does not withhold a
// dashboard the member is already entitled to.
export async function resolveRegistrationAccess(accessToken: string): Promise<AccessContext> {
  try {
    return await requireMemberAccess(accessToken);
  } catch (error) {
    if (error instanceof AccessPolicyError) throw new RegistrationAccessError(error.status, error.message);
    throw new RegistrationAccessError(503, "could not verify member access");
  }
}

async function selectedModulesFor(ctx: AccessContext): Promise<SalesModule[] | null> {
  if (ctx.tier !== "FREE") return null; // unrestricted -- no picker needed
  try {
    return await getSalesModuleSelection(ctx.db, ctx.userId, currentSalesModuleCycleKey());
  } catch (error) {
    if (error instanceof AccessPolicyError) throw new RegistrationAccessError(error.status, error.message);
    throw error;
  }
}

// Consumes exactly one sales_query quota unit for the CALLING top-level
// action. Every function in this module that hits the network more than
// once per logical action (getRegistrationDashboard, and the market
// report orchestration in app/api/report/market/route.ts) must call this
// itself exactly once and pass the resulting ctx/db down to quota-free
// internal fetchers -- never call this per internal fetch.
async function consumeSalesQueryQuota(
  ctx: AccessContext,
  fingerprintParts: Array<string | number | boolean | null | undefined>,
) {
  try {
    return await requireUsage(ctx, "sales_query", ctx.policy.salesQueryDailyLimit, fingerprintParts);
  } catch (error) {
    if (error instanceof AccessPolicyError) throw new RegistrationAccessError(error.status, error.message);
    throw error;
  }
}

// --- Low-level, quota-free row fetcher -----------------------------------
// Never resolves access and never consumes quota -- callers must already
// hold a validated AccessContext and must have accounted for quota
// themselves (once, per logical action) before calling this.
async function fetchDimensionRowsInternal(
  ctx: AccessContext,
  dimension: RegistrationDimension,
  period: string | null | undefined,
  limit: number,
): Promise<any[]> {
  const config = VIEW_CONFIG[dimension];
  const boundedLimit = Math.min(Math.max(limit ?? 100, 1), 500);

  let query = ctx.db.from(config.table).select("*");
  if (period) query = query.eq("period", period);
  const historyStart = historyWindowStart(ctx.tier);
  if (historyStart) query = query.gte("period", historyStart);
  query = query.order(config.order, { ascending: config.ascending ?? true }).limit(boundedLimit);

  const { data, error } = await query;
  if (error) throw new RegistrationAccessError(500, `registration analytics query failed: ${error.message}`);
  return data ?? [];
}

function assertRegistrationDimensionAllowed(ctx: AccessContext, dimension: RegistrationDimension, selectedModules: SalesModule[] | null) {
  if (!isRegistrationDimensionAllowed(dimension, ctx.tier, selectedModules)) {
    throw new RegistrationAccessError(403, `dimension "${dimension}" is not part of this cycle's selected sales modules`);
  }
}

function assertPeriodWithinHistory(ctx: AccessContext, period: string | null | undefined) {
  if (!period) return;
  const start = historyWindowStart(ctx.tier);
  if (start && period < start) {
    throw new RegistrationAccessError(403, `period is outside this account's history window (from ${start})`);
  }
}

// --- Top-level, quota-accounted entry points -----------------------------

// Standalone single-dimension read. One call = one logical action = one
// quota unit (except `coverage`, which is free boot/navigation metadata).
export async function getRegistrationAnalytics(args: {
  accessToken: string;
  dimension: RegistrationDimension;
  period?: string | null;
  limit?: number;
}) {
  const ctx = await resolveRegistrationAccess(args.accessToken);
  const selectedModules = await selectedModulesFor(ctx);
  assertRegistrationDimensionAllowed(ctx, args.dimension, selectedModules);
  assertPeriodWithinHistory(ctx, args.period);

  if (args.dimension !== "coverage") {
    await consumeSalesQueryQuota(ctx, ["dimension", args.dimension, args.period ?? "", String(args.limit ?? 100)]);
  }

  return fetchDimensionRowsInternal(ctx, args.dimension, args.period, args.limit ?? 100);
}

export interface RegistrationDashboard {
  tier: AccessContext["tier"];
  period: string | null;
  coverage: any | null;
  dimensions: Partial<Record<RegistrationDimension, any[]>>;
  quota: Awaited<ReturnType<typeof consumeSalesQueryQuota>>;
}

// The composite "Sales Tools dashboard Run" endpoint: ONE top-level call
// that resolves access, figures out the permitted dimension set, consumes
// exactly ONE sales_query quota unit for the whole run, then fetches
// coverage plus every permitted dimension server-side with no further
// quota calls. Replaces the old client-side 7-call fan-out (1 coverage +
// 6 dimensions), each of which used to try to share one quota unit via a
// client-supplied action id -- the actual bug this rewrite fixes.
export async function getRegistrationDashboard(accessToken: string): Promise<RegistrationDashboard> {
  const ctx = await resolveRegistrationAccess(accessToken);
  const selectedModules = await selectedModulesFor(ctx);

  const coverageRows = await fetchDimensionRowsInternal(ctx, "coverage", null, 100);
  const latest = [...coverageRows].sort((a, b) => String(a.period).localeCompare(String(b.period))).at(-1) ?? null;
  const period = latest ? String(latest.period).slice(0, 10) : null;

  const allowedDimensions = ALL_REGISTRATION_DIMENSIONS.filter((dimension) =>
    isRegistrationDimensionAllowed(dimension, ctx.tier, selectedModules));

  const quota = await consumeSalesQueryQuota(ctx, ["dashboard", period ?? "", allowedDimensions.slice().sort().join(",")]);

  const results = await Promise.all(
    allowedDimensions.map((dimension) => fetchDimensionRowsInternal(ctx, dimension, period, 100)),
  );
  const dimensions: Partial<Record<RegistrationDimension, any[]>> = {};
  allowedDimensions.forEach((dimension, index) => { dimensions[dimension] = results[index]; });

  return { tier: ctx.tier, period, coverage: latest, dimensions, quota };
}

// Boot/navigation metadata, never metered. Takes an already-resolved ctx
// so a caller that needs both this and getRegistrationMarketSlice (i.e.
// app/api/report/market/route.ts) resolves access exactly once per
// request.
export async function getRegistrationAvailablePeriods(ctx: AccessContext): Promise<string[]> {
  let query = ctx.db
    .from("registration_analytics_coverage")
    .select("period")
    .order("period", { ascending: true });
  const historyStart = historyWindowStart(ctx.tier);
  if (historyStart) query = query.gte("period", historyStart);
  const { data, error } = await query;
  if (error) throw new RegistrationAccessError(500, `registration period query failed: ${error.message}`);
  return (data ?? [])
    .map((row: any) => String(row.period).slice(0, 10))
    .filter(Boolean);
}

function normalizeRegistrationToken(value: unknown): string {
  return String(value || "").toLocaleLowerCase().replace(/[^a-z0-9]+/g, "");
}

function canonicalPowertrain(payload: JsonObject | null | undefined): string {
  const powertrains = Array.isArray(payload?.powertrains)
    ? payload.powertrains.map((value: unknown) => String(value || "").trim()).filter(Boolean)
    : [];
  if (!powertrains.length) return "UNKNOWN";
  return powertrains.length === 1 ? powertrains[0] : "MIXED";
}

// Every field the historical model state carries a year baseline for --
// origin_country/import_type (which also walk the sparse monthly_changes
// layer) plus the five that resolve from the baseline alone (see
// lib/historical-model-state.ts's HistoricalModelBaseline doc comment):
// powertrain, market_position, oem_group, brand_origin, market_scope.
// Reading any of them for a period other than "now" from the current
// canonical payload would silently rewrite history -- a nameplate that was
// ICE-only in 2022 reading back as MIXED today because it later gained a
// hybrid variant, an OEM's ownership change appearing to have always been
// true, and so on.
const HISTORICAL_STATE_DIMENSIONS: ReadonlySet<MarketDimension> = new Set([
  "import_type", "origin_country", "powertrain", "market_position",
  "oem_group", "brand_origin", "market_scope",
]);

function needsHistoricalModelState(dimension: MarketDimension, filters: MarketSliceFilters) {
  return HISTORICAL_STATE_DIMENSIONS.has(dimension)
    || Boolean(filters.importTypes?.length)
    || Boolean(filters.originCountries?.length)
    || Boolean(filters.powertrains?.length)
    || Boolean(filters.marketPositions?.length)
    || Boolean(filters.oemGroups?.length)
    || Boolean(filters.brandOrigins?.length)
    || Boolean(filters.marketScopes?.length);
}

export async function fetchRegistrationRows(
  db: any,
  window: MarketPeriodWindow,
  registrationTypes: string[] | undefined,
  keepRegistrationTypeOpen: boolean,
): Promise<any[]> {
  const rows: any[] = [];
  for (let offset = 0; offset < MAX_FACT_ROWS; offset += PAGE_SIZE) {
    // Phase 3 compatibility boundary: registration_reporting_source is
    // shape-identical to `registrations` plus a canonical_model_id
    // passthrough, and transparently serves either legacy `registrations`
    // or the v2 shadow projection depending on
    // registration_serving_state.active_source -- see
    // supabase/migration_v31_registration_v2_serving_and_cutover.sql and
    // docs/vehicle-platform/PHASE3_CUTOVER.md. This is the one place the
    // market-slice path needs to change for the cutover switch to reach it;
    // every dimension view VIEW_CONFIG reads from (registration_monthly_model
    // etc.) is redirected at the SQL layer and needs no change here.
    // canonical_model_id is selected so canonicalizeRegistrationRows can
    // resolve a v2 row directly by canonical id, never requiring a reverse
    // legacy uuid crosswalk for a correctly-resolved v2 model (see below).
    let query = db
      .from("registration_reporting_source")
      .select("period,registration_type,brand_name_raw,model_name_raw,model_id,canonical_model_id,registrations")
      .gte("period", window.from)
      .lte("period", window.to)
      .order("period", { ascending: true })
      .order("brand_name_raw", { ascending: true })
      .order("model_name_raw", { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1);
    if (!keepRegistrationTypeOpen && registrationTypes?.length) {
      query = query.in("registration_type", registrationTypes);
    }
    const { data, error } = await query;
    if (error) throw new RegistrationAccessError(500, `registration fact query failed: ${error.message}`);
    const page = data || [];
    rows.push(...page);
    if (page.length < PAGE_SIZE) return rows;
  }
  throw new RegistrationAccessError(413, `registration market window exceeds ${MAX_FACT_ROWS.toLocaleString()} fact rows`);
}

export async function canonicalizeRegistrationRows(
  db: any,
  rows: any[],
  requireHistoricalModelState: boolean,
): Promise<CanonicalRegistrationFact[]> {
  const [
    { data: modelRows, error: modelError },
    { data: brandRows, error: brandError },
    { data: aliasRows, error: aliasError },
    historicalState,
  ] = await Promise.all([
    db.from("current_vehicle_models")
      .select("canonical_id,tdr_model_id,brand_id,name_en,name_th,segment,body_type,payload")
      .limit(1000),
    db.from("current_vehicle_brands")
      .select("canonical_id,tdr_brand_id,slug,name_en,name_th,payload")
      .limit(500),
    db.from("registration_brand_aliases")
      .select("raw_brand_norm,brand_id")
      .limit(2000),
    getActiveHistoricalModelState(db),
  ]);
  if (modelError) throw new RegistrationAccessError(500, `canonical model query failed: ${modelError.message}`);
  if (brandError) throw new RegistrationAccessError(500, `canonical brand query failed: ${brandError.message}`);
  if (aliasError) throw new RegistrationAccessError(500, `registration brand crosswalk query failed: ${aliasError.message}`);
  if (requireHistoricalModelState && !historicalState) {
    throw new RegistrationAccessError(503, "period-aware model state is not available in the active canonical release");
  }

  const typedModels = (modelRows || []) as CanonicalModelRow[];
  const typedBrands = (brandRows || []) as CanonicalBrandRow[];
  const typedAliases = (aliasRows || []) as RegistrationBrandAliasRow[];

  const modelsByTdrId = new Map<string, CanonicalModelRow>(typedModels
    .filter((row) => row.tdr_model_id)
    .map((row) => [String(row.tdr_model_id), row]));
  const modelsByCanonicalId = new Map<string, CanonicalModelRow>(typedModels
    .filter((row) => row.canonical_id)
    .map((row) => [String(row.canonical_id), row]));
  const brandsByCanonicalId = new Map<string, CanonicalBrandRow>(typedBrands
    .filter((row) => row.canonical_id)
    .map((row) => [String(row.canonical_id), row]));
  const brandsByTdrId = new Map<string, CanonicalBrandRow>(typedBrands
    .filter((row) => row.tdr_brand_id)
    .map((row) => [String(row.tdr_brand_id), row]));
  const brandAliases = new Map<string, string>(typedAliases
    .map((row) => [String(row.raw_brand_norm), String(row.brand_id)]));

  return rows.map((row: any) => {
    // A v2-resolved row carries its own canonical_model_id directly -
    // resolve by that first, with no legacy uuid required. Only a row with
    // no canonical_model_id (every legacy row while active_source =
    // 'legacy', or a v2 row registration_reporting_source could not
    // reverse-crosswalk) falls back to the existing model_id -> tdr_model_id
    // path, preserving legacy behavior unchanged.
    const model = row.canonical_model_id
      ? modelsByCanonicalId.get(String(row.canonical_model_id))
      : row.model_id ? modelsByTdrId.get(String(row.model_id)) : undefined;
    const aliasBrandTdrId = brandAliases.get(normalizeRegistrationToken(row.brand_name_raw));
    const brand = model?.brand_id
      ? brandsByCanonicalId.get(String(model.brand_id))
      : aliasBrandTdrId ? brandsByTdrId.get(aliasBrandTdrId) : undefined;
    const payload = model?.payload || {};
    const brandPayload = brand?.payload || {};
    const canonicalModelId = model?.canonical_id ? String(model.canonical_id) : null;
    const canonicalBrandId = model?.brand_id
      ? String(model.brand_id)
      : brand?.canonical_id ? String(brand.canonical_id) : null;
    const historical = historicalState && canonicalModelId
      ? resolveHistoricalModelState(historicalState, canonicalModelId, String(row.period))
      : null;
    const importType = historical
      ? historical.import_type
      : String(payload.production_type || "UNKNOWN");
    const originCountry = historical
      ? historical.origin_country
      : String(payload.production_country || "UNKNOWN");
    // These five move on generation/model-year timescales rather than
    // mid-year, so -- unlike import/origin above -- the historical answer is
    // the year baseline alone (see HistoricalModelBaseline's doc comment).
    // Reading them from the CURRENT canonical payload for a past period
    // would silently rewrite history: a nameplate that was ICE-only in 2022
    // reading back as MIXED today just because it later gained a hybrid
    // variant, an OEM's ownership change appearing to have always been true.
    const powertrain = historical
      ? historical.powertrain
      : canonicalModelId ? canonicalPowertrain(payload) : "UNKNOWN";
    const marketPosition = historical ? historical.market_position : String(payload.market_position || "UNKNOWN");
    const oemGroup = historical ? historical.oem_group : String(brandPayload.oem_group || "UNKNOWN");
    const brandOrigin = historical ? historical.brand_origin : String(brandPayload.brand_origin || "UNKNOWN");
    const marketScope = historical
      ? historical.market_scope
      : canonicalModelId ? String(payload.market_scope || "UNKNOWN") : canonicalBrandId ? "MIXED" : "UNKNOWN";

    return {
      period: String(row.period).slice(0, 10),
      registration_type: String(row.registration_type || "*"),
      registrations: Number(row.registrations || 0),
      canonical_model_id: canonicalModelId,
      canonical_brand_id: canonicalBrandId,
      brand_name: String(brand?.name_en || brand?.name_th || row.brand_name_raw || "UNKNOWN"),
      model_name: String(model?.name_en || model?.name_th || row.model_name_raw || "UNKNOWN"),
      segment: String(model?.segment || "UNKNOWN"),
      body_type: String(model?.body_type || "UNKNOWN"),
      powertrain,
      oem_group: oemGroup,
      market_position: marketPosition,
      import_type: importType,
      origin_country: originCountry,
      brand_origin: brandOrigin,
      market_scope: marketScope,
      raw_brand_name: String(row.brand_name_raw || ""),
      raw_model_name: String(row.model_name_raw || ""),
      brand_mapped: Boolean(canonicalBrandId),
      canonically_mapped: Boolean(canonicalModelId),
    };
  });
}

// Lower-level market-slice fetcher: takes an ALREADY-RESOLVED AccessContext
// and never consumes quota itself. app/api/report/market/route.ts resolves
// access and consumes quota exactly ONCE per "Update market" request, then
// calls this as many times as it genuinely needs data (current window,
// optional comparison window, trend months) -- none of those internal
// calls pay again. Module/history validation stays here as defense in
// depth (it is not a billing action, so repeating it per call is fine).
/** Whether a filter set asks for a subset rather than the whole market.
 *
 *  registrationTypes is deliberately excluded: it selects which DLT vehicle
 *  classes are in scope at all, which every tier needs to read a coherent
 *  total, and it is not a way of singling anything out. */
function hasNarrowingFilter(filters: MarketSliceFilters | undefined): boolean {
  if (!filters) return false;
  const narrowing: (keyof MarketSliceFilters)[] = [
    "brandIds", "modelIds", "segments", "bodyTypes", "powertrains",
    "oemGroups", "importTypes", "originCountries", "brandOrigins",
    "marketPositions", "marketScopes",
  ];
  return narrowing.some((key) => {
    const value = filters[key] as unknown;
    return Array.isArray(value) && value.length > 0;
  });
}

export async function getRegistrationMarketSlice(args: {
  ctx: AccessContext;
  dimension: MarketDimension;
  window: MarketPeriodWindow;
  filters?: MarketSliceFilters;
  includeUnmapped?: boolean;
  limit?: number;
}): Promise<MarketSliceRow[]> {
  const { ctx } = args;
  const selectedModules = await selectedModulesFor(ctx);
  if (!isMarketDimensionAllowed(args.dimension, ctx.tier, selectedModules)) {
    throw new RegistrationAccessError(403, `dimension "${args.dimension}" is not available on this account's plan`);
  }
  const historyStart = historyWindowStart(ctx.tier);
  if (historyStart && args.window.from < historyStart) {
    throw new RegistrationAccessError(403, `window is outside this account's history window (from ${historyStart})`);
  }
  // Narrowing a slice to chosen brands, models or segments is the difference
  // between reading the market and interrogating it, so it is checked here
  // where the rows are actually read rather than only in the controls. A
  // caller that hides the inputs but still sends the parameter gets a 403.
  if (!areMarketFiltersAllowed(ctx.tier) && hasNarrowingFilter(args.filters)) {
    throw new RegistrationAccessError(403, "filtering a market slice is not available on this account's plan");
  }

  const db = ctx.db;
  const filters = args.filters || {};
  const rows = await fetchRegistrationRows(
    db,
    args.window,
    filters.registrationTypes,
    args.dimension === "registration_type",
  );
  const facts = await canonicalizeRegistrationRows(
    db,
    rows,
    needsHistoricalModelState(args.dimension, filters),
  );
  return sliceMarketFacts({
    facts,
    dimension: args.dimension,
    filters,
    includeUnmapped: args.includeUnmapped,
    limit: args.limit,
  });
}

// The ONE quota-consuming call site for the whole Market Comparison
// request -- app/api/report/market/route.ts calls this exactly once per
// "Update market" request, before any getRegistrationMarketSlice calls
// (current window, comparison window, trend months all follow and pay
// nothing further).
export async function consumeMarketReportQuota(
  ctx: AccessContext,
  fingerprintParts: Array<string | number | boolean | null | undefined>,
) {
  return consumeSalesQueryQuota(ctx, ["market", ...fingerprintParts]);
}
