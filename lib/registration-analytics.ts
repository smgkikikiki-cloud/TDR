import { adminDb } from "@/lib/supabase";
import {
  sliceMarketFacts,
  type CanonicalRegistrationFact,
  type MarketDimension,
  type MarketPeriodWindow,
  type MarketSliceFilters,
  type MarketSliceRow,
} from "@/lib/registration-market";

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

export type RegistrationDimension =
  | "coverage"
  | "brand"
  | "model"
  | "mom"
  | "segment"
  | "powertrain"
  | "chinese-bev";

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

const ACTIVE_STATUSES = new Set(["ACTIVE", "TRIALING", "GRACE"]);
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

async function requireRegistrationEntitlement(accessToken: string) {
  const db = adminDb();
  if (!db) throw new RegistrationAccessError(503, "registration analytics database is not configured");

  const { data: userData, error: userError } = await db.auth.getUser(accessToken);
  if (userError || !userData.user) {
    throw new RegistrationAccessError(401, "invalid or expired member session");
  }

  const { data: entitlement, error: entitlementError } = await db
    .from("tdr_entitlements")
    .select("status,valid_until")
    .eq("user_id", userData.user.id)
    .eq("product", "registration_full")
    .maybeSingle();

  if (entitlementError) {
    throw new RegistrationAccessError(503, "could not verify registration entitlement");
  }

  const validUntil = entitlement?.valid_until ? new Date(entitlement.valid_until) : null;
  const expired = validUntil ? validUntil.getTime() <= Date.now() : false;
  if (!entitlement || !ACTIVE_STATUSES.has(entitlement.status) || expired) {
    throw new RegistrationAccessError(403, "registration analytics entitlement required");
  }

  return db;
}

export async function getRegistrationAnalytics(args: {
  accessToken: string;
  dimension: RegistrationDimension;
  period?: string | null;
  limit?: number;
}) {
  const db = await requireRegistrationEntitlement(args.accessToken);
  const config = VIEW_CONFIG[args.dimension];
  const limit = Math.min(Math.max(args.limit ?? 100, 1), 500);

  let query = db.from(config.table).select("*");
  if (args.period) query = query.eq("period", args.period);
  query = query.order(config.order, { ascending: config.ascending ?? true }).limit(limit);

  const { data, error } = await query;
  if (error) throw new RegistrationAccessError(500, `registration analytics query failed: ${error.message}`);

  return data ?? [];
}

export async function getRegistrationAvailablePeriods(accessToken: string): Promise<string[]> {
  const db = await requireRegistrationEntitlement(accessToken);
  const { data, error } = await db
    .from("registration_analytics_coverage")
    .select("period")
    .order("period", { ascending: true });
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

async function fetchRegistrationRows(
  db: any,
  window: MarketPeriodWindow,
  registrationTypes: string[] | undefined,
  keepRegistrationTypeOpen: boolean,
): Promise<any[]> {
  const rows: any[] = [];
  for (let offset = 0; offset < MAX_FACT_ROWS; offset += PAGE_SIZE) {
    let query = db
      .from("registrations")
      .select("period,registration_type,brand_name_raw,model_name_raw,model_id,registrations")
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

async function canonicalizeRegistrationRows(db: any, rows: any[]): Promise<CanonicalRegistrationFact[]> {
  const [{ data: modelRows, error: modelError }, { data: brandRows, error: brandError }, { data: aliasRows, error: aliasError }] = await Promise.all([
    db.from("current_vehicle_models")
      .select("canonical_id,tdr_model_id,brand_id,name_en,name_th,segment,body_type,payload")
      .limit(1000),
    db.from("current_vehicle_brands")
      .select("canonical_id,tdr_brand_id,slug,name_en,name_th,payload")
      .limit(500),
    db.from("registration_brand_aliases")
      .select("raw_brand_norm,brand_id")
      .limit(2000),
  ]);
  if (modelError) throw new RegistrationAccessError(500, `canonical model query failed: ${modelError.message}`);
  if (brandError) throw new RegistrationAccessError(500, `canonical brand query failed: ${brandError.message}`);
  if (aliasError) throw new RegistrationAccessError(500, `registration brand crosswalk query failed: ${aliasError.message}`);

  const typedModels = (modelRows || []) as CanonicalModelRow[];
  const typedBrands = (brandRows || []) as CanonicalBrandRow[];
  const typedAliases = (aliasRows || []) as RegistrationBrandAliasRow[];

  const modelsByTdrId = new Map<string, CanonicalModelRow>(typedModels
    .filter((row) => row.tdr_model_id)
    .map((row) => [String(row.tdr_model_id), row]));
  const brandsByCanonicalId = new Map<string, CanonicalBrandRow>(typedBrands
    .filter((row) => row.canonical_id)
    .map((row) => [String(row.canonical_id), row]));
  const brandsByTdrId = new Map<string, CanonicalBrandRow>(typedBrands
    .filter((row) => row.tdr_brand_id)
    .map((row) => [String(row.tdr_brand_id), row]));
  const brandAliases = new Map<string, string>(typedAliases
    .map((row) => [String(row.raw_brand_norm), String(row.brand_id)]));

  return rows.map((row: any) => {
    const model = row.model_id ? modelsByTdrId.get(String(row.model_id)) : undefined;
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
      powertrain: canonicalModelId ? canonicalPowertrain(payload) : "UNKNOWN",
      oem_group: String(brandPayload.oem_group || "UNKNOWN"),
      market_position: String(payload.market_position || "UNKNOWN"),
      import_type: String(payload.production_type || "UNKNOWN"),
      origin_country: String(payload.production_country || "UNKNOWN"),
      brand_origin: String(brandPayload.brand_origin || "UNKNOWN"),
      market_scope: canonicalModelId ? String(payload.market_scope || "UNKNOWN") : canonicalBrandId ? "MIXED" : "UNKNOWN",
      raw_brand_name: String(row.brand_name_raw || ""),
      raw_model_name: String(row.model_name_raw || ""),
      brand_mapped: Boolean(canonicalBrandId),
      canonically_mapped: Boolean(canonicalModelId),
    };
  });
}

export async function getRegistrationMarketSlice(args: {
  accessToken: string;
  dimension: MarketDimension;
  window: MarketPeriodWindow;
  filters?: MarketSliceFilters;
  includeUnmapped?: boolean;
  limit?: number;
}): Promise<MarketSliceRow[]> {
  const db = await requireRegistrationEntitlement(args.accessToken);
  const filters = args.filters || {};
  const rows = await fetchRegistrationRows(
    db,
    args.window,
    filters.registrationTypes,
    args.dimension === "registration_type",
  );
  const facts = await canonicalizeRegistrationRows(db, rows);
  return sliceMarketFacts({
    facts,
    dimension: args.dimension,
    filters,
    includeUnmapped: args.includeUnmapped,
    limit: args.limit,
  });
}
