import { adminDb } from "@/lib/supabase";
import { getActiveHistoricalModelState, resolveHistoricalModelState } from "@/lib/historical-model-state";
import {
  sliceMarketFacts,
  type CanonicalRegistrationFact,
  type MarketDimension,
  type MarketPeriodWindow,
  type MarketSliceFilters,
  type MarketSliceRow,
} from "@/lib/registration-market";

const PAGE_SIZE = 1000;
const MAX_FACT_ROWS = 50000;

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
type RegistrationBrandAliasRow = { raw_brand_norm: string; brand_id: string };

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

function needsHistoricalImportOrigin(dimension: MarketDimension, filters: MarketSliceFilters) {
  return dimension === "import_type"
    || dimension === "origin_country"
    || Boolean(filters.importTypes?.length)
    || Boolean(filters.originCountries?.length);
}

async function fetchRows(window: MarketPeriodWindow, filters: MarketSliceFilters, dimension: MarketDimension) {
  const db = adminDb();
  if (!db) throw new Error("admin database is not configured");
  const rows: any[] = [];
  for (let offset = 0; offset < MAX_FACT_ROWS; offset += PAGE_SIZE) {
    let query = db.from("registrations")
      .select("period,registration_type,brand_name_raw,model_name_raw,model_id,registrations,mapping_method")
      .gte("period", window.from).lte("period", window.to)
      .order("period", { ascending: true })
      .order("brand_name_raw", { ascending: true })
      .order("model_name_raw", { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1);
    if (dimension !== "registration_type" && filters.registrationTypes?.length) {
      query = query.in("registration_type", filters.registrationTypes);
    }
    const { data, error } = await query;
    if (error) throw new Error(`registration fact query failed: ${error.message}`);
    const page = data || [];
    rows.push(...page);
    if (page.length < PAGE_SIZE) return { db, rows };
  }
  throw new Error(`registration market window exceeds ${MAX_FACT_ROWS.toLocaleString()} fact rows`);
}

async function canonicalize(
  db: any,
  rows: any[],
  requireHistoricalImportOrigin: boolean,
): Promise<CanonicalRegistrationFact[]> {
  const [
    { data: modelRows, error: modelError },
    { data: brandRows, error: brandError },
    { data: aliasRows, error: aliasError },
    historicalState,
  ] = await Promise.all([
    db.from("current_vehicle_models")
      .select("canonical_id,tdr_model_id,brand_id,name_en,name_th,segment,body_type,payload").limit(1000),
    db.from("current_vehicle_brands")
      .select("canonical_id,tdr_brand_id,slug,name_en,name_th,payload").limit(500),
    db.from("registration_brand_aliases").select("raw_brand_norm,brand_id").limit(2000),
    getActiveHistoricalModelState(db),
  ]);
  if (modelError) throw new Error(`canonical model query failed: ${modelError.message}`);
  if (brandError) throw new Error(`canonical brand query failed: ${brandError.message}`);
  if (aliasError) throw new Error(`registration brand crosswalk query failed: ${aliasError.message}`);
  if (requireHistoricalImportOrigin && !historicalState) {
    throw new Error("period-aware import/origin state is not available in the active canonical release");
  }

  const models = (modelRows || []) as CanonicalModelRow[];
  const brands = (brandRows || []) as CanonicalBrandRow[];
  const aliases = (aliasRows || []) as RegistrationBrandAliasRow[];
  const modelsByTdrId = new Map(models.filter((row) => row.tdr_model_id).map((row) => [String(row.tdr_model_id), row]));
  const brandsByCanonicalId = new Map(brands.filter((row) => row.canonical_id).map((row) => [String(row.canonical_id), row]));
  const brandsByTdrId = new Map(brands.filter((row) => row.tdr_brand_id).map((row) => [String(row.tdr_brand_id), row]));
  const brandAliases = new Map(aliases.map((row) => [String(row.raw_brand_norm), String(row.brand_id)]));

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
    const modelScope = String(payload.market_scope || "UNKNOWN");
    const historical = historicalState && canonicalModelId
      ? resolveHistoricalModelState(historicalState, canonicalModelId, String(row.period))
      : null;
    const importType = historical
      ? historical.import_type
      : String(payload.production_type || "UNKNOWN");
    const originCountry = historical
      ? historical.origin_country
      : String(payload.production_country || "UNKNOWN");

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
      import_type: importType,
      origin_country: originCountry,
      brand_origin: String(brandPayload.brand_origin || "UNKNOWN"),
      market_scope: canonicalModelId ? modelScope : canonicalBrandId ? "MIXED" : "UNKNOWN",
      raw_brand_name: String(row.brand_name_raw || ""),
      raw_model_name: String(row.model_name_raw || ""),
      brand_mapped: Boolean(canonicalBrandId),
      canonically_mapped: Boolean(canonicalModelId),
    };
  });
}

export async function getAdminRegistrationCoverage() {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db.from("registration_analytics_coverage")
    .select("period,raw_rows,total_registrations,mapped_rows,mapped_registrations,mapped_unit_pct")
    .order("period", { ascending: true }).limit(240);
  if (error) throw new Error(`registration coverage query failed: ${error.message}`);
  return data || [];
}

export async function getAdminMarketOptions() {
  const db = adminDb();
  if (!db) return { brands: [], models: [] };
  const [{ data: brands, error: brandError }, { data: models, error: modelError }] = await Promise.all([
    db.from("current_vehicle_brands").select("canonical_id,name_en,name_th").order("name_en").limit(500),
    db.from("current_vehicle_models").select("canonical_id,brand_id,name_en,name_th,segment,body_type,payload").order("name_en").limit(1000),
  ]);
  if (brandError) throw new Error(`brand options query failed: ${brandError.message}`);
  if (modelError) throw new Error(`model options query failed: ${modelError.message}`);
  return {
    brands: (brands || []).map((row: any) => ({ id: String(row.canonical_id), name: String(row.name_en || row.name_th || row.canonical_id) })),
    models: (models || []).map((row: any) => ({
      id: String(row.canonical_id), brandId: String(row.brand_id || ""),
      name: String(row.name_en || row.name_th || row.canonical_id),
      segment: row.segment ? String(row.segment) : null,
      bodyType: row.body_type ? String(row.body_type) : null,
      powertrain: canonicalPowertrain((row.payload || {}) as JsonObject),
    })),
  };
}

export async function getAdminRegistrationMarketSlice(args: {
  dimension: MarketDimension;
  window: MarketPeriodWindow;
  filters?: MarketSliceFilters;
  includeUnmapped?: boolean;
  limit?: number;
}): Promise<MarketSliceRow[]> {
  const filters = args.filters || {};
  const { db, rows } = await fetchRows(args.window, filters, args.dimension);
  const facts = await canonicalize(db, rows, needsHistoricalImportOrigin(args.dimension, filters));
  return sliceMarketFacts({ facts, dimension: args.dimension, filters, includeUnmapped: args.includeUnmapped, limit: args.limit });
}

export async function getAdminUnmappedRegistrationSummary(limit = 200) {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db.from("registrations")
    .select("period,registration_type,brand_name_raw,model_name_raw,registrations,mapping_method")
    .is("model_id", null).order("period", { ascending: false }).limit(5000);
  if (error) throw new Error(`unmapped registration query failed: ${error.message}`);
  const grouped = new Map<string, any>();
  for (const row of data || []) {
    const key = `${row.registration_type}|${row.brand_name_raw}|${row.model_name_raw}`;
    const current = grouped.get(key) || {
      registration_type: row.registration_type,
      brand_name_raw: row.brand_name_raw,
      model_name_raw: row.model_name_raw,
      registrations: 0,
      months: 0,
      latest_period: row.period,
      mapping_method: row.mapping_method,
    };
    current.registrations += Number(row.registrations || 0);
    current.months += 1;
    if (String(row.period) > String(current.latest_period)) current.latest_period = row.period;
    grouped.set(key, current);
  }
  return [...grouped.values()]
    .sort((a, b) => b.registrations - a.registrations || String(a.brand_name_raw).localeCompare(String(b.brand_name_raw)))
    .slice(0, Math.max(1, Math.min(limit, 1000)));
}
