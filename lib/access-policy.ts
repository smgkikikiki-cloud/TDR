// Single authoritative access-policy module: tier definitions, per-tier
// quotas/allowances, Asia/Bangkok cycle-key computation, and the Free-tier
// sales-module catalog. Pure logic only (no `@/` imports, no DB calls) so
// it can be unit-tested by scripts/check-access-policy.ts using this
// repo's plain-Node `--experimental-strip-types` test convention, which
// cannot resolve the `@/` bundler alias. Server-side wiring (DB reads,
// token resolution, atomic quota consumption) lives in
// lib/access-policy-server.ts.

export type Tier = "FREE" | "INDIVIDUAL" | "PRO";

export type UsageMetric = "vehicle_compare" | "sales_query" | "research_full" | "pdf_export";

export const USAGE_METRICS: UsageMetric[] = ["vehicle_compare", "sales_query", "research_full", "pdf_export"];

// Daily metrics reset at Bangkok midnight; monthly metrics reset at the
// first of the Bangkok month. Changing a metric's cadence here is the only
// place that needs to change -- period-key and reset-at computation both
// read this map.
export const METRIC_CADENCE: Record<UsageMetric, "daily" | "monthly"> = {
  vehicle_compare: "daily",
  sales_query: "daily",
  research_full: "monthly",
  pdf_export: "monthly",
};

// The six selectable Sales Tools modules. These correspond 1:1 to the six
// non-"coverage" dimensions already exposed by lib/registration-analytics.ts
// (`brand`, `model`, `mom`, `segment`, `powertrain`, `chinese-bev`);
// `coverage` itself is boot/navigation metadata (which periods exist), not
// a selectable module, so it is always available regardless of selection.
export const SALES_MODULES = [
  "brand_share",
  "model_share",
  "month_on_month",
  "segment_share",
  "powertrain_share",
  "chinese_bev_rank",
] as const;

export type SalesModule = (typeof SALES_MODULES)[number];

export const FREE_SALES_MODULE_PICK_COUNT = 4;

// Maps a registration-analytics dimension to the sales module that gates
// it for the Free tier. `coverage` maps to null (always allowed). Market
// dimensions with no equivalent in the six-module catalog (body_type,
// oem_group, registration_type, import_type, origin_country, brand_origin,
// market_scope) also map to null-but-restricted: see
// isMarketDimensionAllowedForFree below, which treats them as
// paid-tier-only advanced filters rather than part of the 4-of-6 picker.
export const REGISTRATION_DIMENSION_MODULE: Record<string, SalesModule | null> = {
  coverage: null,
  brand: "brand_share",
  model: "model_share",
  mom: "month_on_month",
  segment: "segment_share",
  powertrain: "powertrain_share",
  "chinese-bev": "chinese_bev_rank",
};

// Market-slice dimensions that reuse one of the six modules directly.
// Everything else in MarketDimension (body_type, oem_group,
// registration_type, import_type, origin_country, brand_origin,
// market_scope) is an advanced filter outside the 4-of-6 picker's scope
// and is Individual/Pro only on the Free tier -- a product decision made
// here in the absence of an explicit mapping from the spec, and called
// out as such in the delivery report.
export const MARKET_DIMENSION_MODULE: Record<string, SalesModule | null> = {
  model: "model_share",
  brand: "brand_share",
  segment: "segment_share",
  powertrain: "powertrain_share",
};

export interface TierPolicy {
  tier: Tier;
  label: string;
  compareDailyLimit: number | null;
  salesQueryDailyLimit: number | null;
  salesModulePickCount: number | null; // null = all modules available, no picker needed
  historyWindow: "current_calendar_year" | "rolling_24_months" | "full";
  researchAccess: "preview" | "full";
  researchFullMonthlyLimit: number | null;
  pdfMonthlyLimit: number | null;
  pdfWatermark: boolean;
  apiAccess: false;
  rawStructuredExport: false;
}

export const TIER_POLICIES: Record<Tier, TierPolicy> = {
  FREE: {
    tier: "FREE",
    label: "Free",
    compareDailyLimit: 3,
    salesQueryDailyLimit: 10,
    salesModulePickCount: FREE_SALES_MODULE_PICK_COUNT,
    historyWindow: "current_calendar_year",
    researchAccess: "preview",
    researchFullMonthlyLimit: 0,
    pdfMonthlyLimit: 1,
    pdfWatermark: true,
    apiAccess: false,
    rawStructuredExport: false,
  },
  INDIVIDUAL: {
    tier: "INDIVIDUAL",
    label: "Individual",
    compareDailyLimit: null,
    salesQueryDailyLimit: null,
    salesModulePickCount: null,
    historyWindow: "rolling_24_months",
    researchAccess: "full",
    researchFullMonthlyLimit: 3,
    pdfMonthlyLimit: 10,
    pdfWatermark: false,
    apiAccess: false,
    rawStructuredExport: false,
  },
  PRO: {
    tier: "PRO",
    label: "Pro",
    compareDailyLimit: null,
    salesQueryDailyLimit: null,
    salesModulePickCount: null,
    historyWindow: "full",
    researchAccess: "full",
    researchFullMonthlyLimit: null,
    pdfMonthlyLimit: null,
    pdfWatermark: false,
    apiAccess: false,
    rawStructuredExport: false,
  },
};

export function getPolicy(tier: Tier): TierPolicy {
  return TIER_POLICIES[tier];
}

// --- Reserved high-value capabilities (richer than boolean access) ------
//
// Some future Sales Tools capabilities (starting with provincial
// registration) don't fit "on for this tier / off for that tier": a
// capability can be entirely unbuilt yet still need a visible "coming
// soon" placeholder, then launch as a locked teaser, then a
// commercially-limited tier, then a full tier, then a bespoke Corporate
// scope -- all before any numeric quota/limit has been decided. This
// registry is the one place that ladder lives, so a route or component
// never hand-rolls its own tier-check for a reserved capability.
export type FeatureState = "unavailable" | "teaser" | "limited" | "full" | "tailored";

// Stable, generic keys only -- this union is meant to grow as more
// high-value capabilities get reserved this way.
export type FeatureKey = "provincial_registration";

// Corporate is sales-assisted, not a self-service Tier (see Tier above),
// but still needs a place in a feature's ladder.
export type FeatureAudience = Tier | "CORPORATE";

export interface FeatureDefinition {
  key: FeatureKey;
  label: string;
  labelTh: string;
  /**
   * Global kill switch. While false, the feature resolves to `teaser` for
   * every audience regardless of `stateByAudience` below -- the launch
   * ladder only takes effect once the underlying data product is real and
   * this is flipped by a future change here, not by any per-request logic.
   */
  released: boolean;
  /** The intended ladder once `released` is true. Not yet commercially
   *  finalized for every audience -- see the field-level comments below.
   *  Never encode invented numeric limits (quotas, province counts,
   *  history windows) here; `FeatureState` is deliberately just a label. */
  stateByAudience: Record<FeatureAudience, FeatureState>;
  /** Whether choosing this feature should ever occupy one of the Free
   *  tier's 4-of-6 sales-module slots. false while unreleased. */
  countsTowardSalesModuleSelection: boolean;
  /** Whether using this feature should ever consume a usage-quota metric.
   *  false while unreleased (and while no metric has been decided for it). */
  consumesQuota: boolean;
}

export const FEATURES: Record<FeatureKey, FeatureDefinition> = {
  provincial_registration: {
    key: "provincial_registration",
    label: "Provincial Registration",
    labelTh: "ยอดจดทะเบียนรายจังหวัด",
    released: false,
    // Intended future ladder (per product direction, 2026-09): Free sees a
    // locked teaser; Plus/Individual gets *some* real use once released,
    // exact scope/limits not decided yet (never invent one); Pro gets the
    // full professional experience (province coverage, multi-province
    // compare, historical analysis, deeper filtering) *subject to whatever
    // the data product actually supports at release time*; Corporate may
    // get bespoke geographic/team workflows. None of this ladder is live
    // yet -- `released: false` above forces `teaser` for everyone today.
    stateByAudience: {
      FREE: "teaser",
      INDIVIDUAL: "limited",
      PRO: "full",
      CORPORATE: "tailored",
    },
    countsTowardSalesModuleSelection: false,
    consumesQuota: false,
  },
};

export function resolveFeatureState(featureKey: FeatureKey, audience: FeatureAudience): FeatureState {
  const feature = FEATURES[featureKey];
  if (!feature.released) return "teaser";
  return feature.stateByAudience[audience];
}

// --- Tier resolution from raw tdr_entitlements rows -------------------

const ACTIVE_ENTITLEMENT_STATUSES = new Set(["ACTIVE", "TRIALING", "GRACE"]);

// Legacy product name from before this tiered model existed. Existing
// registration_monthly/registration_full subscribers must keep full
// access; they are treated as Pro-equivalent until an explicit future
// migration, per product decision -- never rewritten in place.
export const LEGACY_REGISTRATION_PRODUCT = "registration_full";
export const TIER_PRODUCT: Record<Exclude<Tier, "FREE">, string> = {
  INDIVIDUAL: "tier_individual",
  PRO: "tier_pro",
};

export interface EntitlementRow {
  product: string;
  status: string;
  valid_until: string | null;
}

function isEntitlementRowActive(row: EntitlementRow, now: Date): boolean {
  if (!ACTIVE_ENTITLEMENT_STATUSES.has(row.status)) return false;
  if (!row.valid_until) return true;
  return new Date(row.valid_until).getTime() > now.getTime();
}

export function resolveTierFromEntitlements(rows: EntitlementRow[], now: Date = new Date()): Tier {
  const active = rows.filter((row) => isEntitlementRowActive(row, now));
  const hasPro = active.some((row) => row.product === TIER_PRODUCT.PRO || row.product === LEGACY_REGISTRATION_PRODUCT);
  if (hasPro) return "PRO";
  const hasIndividual = active.some((row) => row.product === TIER_PRODUCT.INDIVIDUAL);
  if (hasIndividual) return "INDIVIDUAL";
  return "FREE";
}

// --- Asia/Bangkok cycle-key computation ---------------------------------
//
// Thailand has no DST, but we still resolve via Intl rather than a fixed
// UTC+7 offset shift so this stays correct if the runtime's tz database
// changes and remains readable at the call site.

function bangkokParts(date: Date): { year: number; month: number; day: number } {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Bangkok",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = formatter.formatToParts(date);
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  return { year: get("year"), month: get("month"), day: get("day") };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function dailyPeriodKey(date: Date = new Date()): string {
  const { year, month, day } = bangkokParts(date);
  return `${year}-${pad(month)}-${pad(day)}`;
}

export function monthlyPeriodKey(date: Date = new Date()): string {
  const { year, month } = bangkokParts(date);
  return `${year}-${pad(month)}`;
}

export function periodKeyForMetric(metric: UsageMetric, date: Date = new Date()): string {
  return METRIC_CADENCE[metric] === "daily" ? dailyPeriodKey(date) : monthlyPeriodKey(date);
}

// Default sales-module selection cycle = calendar month in Asia/Bangkok.
// This is the one policy-configurable seam the spec asks for: change this
// function (and only this function) to move to a different cycle length
// without any schema change, since tdr_sales_module_selection.cycle_key is
// stored as an opaque string.
export function currentSalesModuleCycleKey(date: Date = new Date()): string {
  return monthlyPeriodKey(date);
}

// resets_at for a quota response: the next Bangkok-local boundary for the
// metric's cadence, expressed as a UTC ISO timestamp.
export function resetsAtForMetric(metric: UsageMetric, date: Date = new Date()): string {
  const { year, month, day } = bangkokParts(date);
  // Asia/Bangkok is a fixed UTC+7 offset (no DST), so the boundary instant
  // can be computed directly from the Bangkok-local calendar date.
  const BANGKOK_OFFSET_MS = 7 * 60 * 60 * 1000;
  if (METRIC_CADENCE[metric] === "daily") {
    const nextMidnightBangkokLocal = Date.UTC(year, month - 1, day + 1, 0, 0, 0);
    return new Date(nextMidnightBangkokLocal - BANGKOK_OFFSET_MS).toISOString();
  }
  const nextMonthStartBangkokLocal = Date.UTC(year, month, 1, 0, 0, 0);
  return new Date(nextMonthStartBangkokLocal - BANGKOK_OFFSET_MS).toISOString();
}

// --- History window enforcement -----------------------------------------

// Returns the earliest period (YYYY-MM-DD) a given tier may read, or null
// for "no lower bound" (Pro: full available history).
export function historyWindowStart(tier: Tier, now: Date = new Date()): string | null {
  const policy = getPolicy(tier);
  const { year, month } = bangkokParts(now);
  if (policy.historyWindow === "full") return null;
  if (policy.historyWindow === "current_calendar_year") {
    return `${year}-01-01`;
  }
  // rolling_24_months: current month plus the 23 preceding months.
  const startMonthIndex = month - 1 - 23; // 0-based month arithmetic
  const startDate = new Date(Date.UTC(year, startMonthIndex, 1));
  return `${startDate.getUTCFullYear()}-${pad(startDate.getUTCMonth() + 1)}-01`;
}

export function isPeriodWithinHistoryWindow(tier: Tier, period: string, now: Date = new Date()): boolean {
  const start = historyWindowStart(tier, now);
  if (!start) return true;
  return period >= start;
}

// --- Sales-module selection validation -----------------------------------

export function isKnownSalesModule(value: string): value is SalesModule {
  return (SALES_MODULES as readonly string[]).includes(value);
}

export function validateSalesModuleSelection(modules: string[], pickCount: number): string | null {
  const unique = new Set(modules);
  if (unique.size !== modules.length) return "duplicate module in selection";
  if (modules.length !== pickCount) return `exactly ${pickCount} modules must be selected`;
  for (const module of modules) {
    if (!isKnownSalesModule(module)) return `unknown sales module: ${module}`;
  }
  return null;
}

export function isRegistrationDimensionAllowed(
  dimension: string,
  tier: Tier,
  selectedModules: SalesModule[] | null,
): boolean {
  if (tier !== "FREE") return true;
  const requiredModule = REGISTRATION_DIMENSION_MODULE[dimension];
  if (requiredModule === null || requiredModule === undefined) return true;
  return Boolean(selectedModules?.includes(requiredModule));
}

export function isMarketDimensionAllowed(
  dimension: string,
  tier: Tier,
  selectedModules: SalesModule[] | null,
): boolean {
  if (tier !== "FREE") return true;
  const requiredModule = MARKET_DIMENSION_MODULE[dimension];
  // Dimensions with no module mapping at all (body_type, oem_group,
  // registration_type, import_type, origin_country, brand_origin,
  // market_scope) are advanced filters reserved for paid tiers.
  if (requiredModule === undefined) return false;
  if (requiredModule === null) return true;
  return Boolean(selectedModules?.includes(requiredModule));
}
