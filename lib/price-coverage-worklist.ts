import targetsRegistry from "@/automotive/vehicle_master/vehreg/data/2026/market/pricefeed/targets.json";
import { defaultMarketPeriod, periodKey } from "@/lib/member-market";
import { priceCoverageDecisions } from "@/lib/price-coverage-review";

export type PriceCoverageBlocker =
  | "UNRESOLVED_MODEL_LIFECYCLE"
  | "NO_MARKET_TRIM"
  | "UNRESOLVED_TRIM_LIFECYCLE"
  | "MISSING_LIST_PRICE";

type RetailLifecycle = "CURRENT" | "HISTORICAL" | "UNVERIFIED";

export type PriceCoverageWorkItem = {
  canonicalModelId: string;
  brand: string;
  model: string;
  modelStatus: RetailLifecycle;
  blocker: PriceCoverageBlocker;
  totalTrims: number;
  currentTrims: number;
  historicalTrims: number;
  unverifiedTrims: number;
  pricedTrims: number;
  missingTrims: number;
  deferredTrims: number;
  actionableMissingTrims: number;
  registrations3m: number;
  registrationSharePct: number;
  seedMinThb: number | null;
  seedMaxThb: number | null;
  seedHintCount: number;
  oemTargetCount: number;
};

type PriceCoverageBaseRow = Omit<PriceCoverageWorkItem, "registrationSharePct" | "blocker"> & {
  blocker: PriceCoverageBlocker | null;
};

export type PriceCoverageWorklist = {
  periods: string[];
  canonicalModels: number;
  retailRelevantModels: number;
  currentModels: number;
  historicalModels: number;
  unverifiedModels: number;
  modelsWithTrims: number;
  modelsWithoutTrims: number;
  readyModels: number;
  modelCoveragePct: number;
  mappedRegistrations3m: number;
  readyRegistrations3m: number;
  registrationCoveragePct3m: number;
  items: PriceCoverageWorkItem[];
};

type JsonObject = Record<string, unknown>;

function numberOrNull(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function lifecycle(value: unknown): RetailLifecycle {
  // Exact uppercase is deliberate. Old serving releases emitted lowercase
  // `current` by default; accepting it would silently reintroduce the bug this
  // worklist is meant to expose.
  return value === "CURRENT" || value === "HISTORICAL" || value === "UNVERIFIED"
    ? value
    : "UNVERIFIED";
}

function canonicalModelLifecycle(model: any): RetailLifecycle {
  // Canonical Model.retail_status is the authority. Legacy editorial `status`
  // in the serving row is not allowed to promote an unreviewed model.
  return lifecycle(model?.payload?.retail_status);
}

function variantSeedPrices(payload: JsonObject | null | undefined): number[] {
  if (!payload) return [];
  const prices: number[] = [];
  const add = (value: unknown) => { const number = numberOrNull(value); if (number != null) prices.push(number); };
  add(payload.price_min_thb);
  add(payload.price_max_thb);
  const variants = Array.isArray(payload.variants) ? payload.variants : [];
  for (const variant of variants) {
    if (!variant || typeof variant !== "object") continue;
    add((variant as JsonObject).price_thb);
  }
  return prices;
}

function targetCountsByModel(): Map<string, number> {
  const counts = new Map<string, number>();
  const rows = Array.isArray((targetsRegistry as any)?.targets) ? (targetsRegistry as any).targets : [];
  for (const row of rows) {
    const modelId = String(row?.model_hint || "").trim();
    if (!modelId || row?.enabled === false) continue;
    counts.set(modelId, (counts.get(modelId) || 0) + 1);
  }
  return counts;
}

function actualCurrentPrice(row: any): number | null {
  // JSONB `null` is not SQL NULL, so presence of current_list_price alone is
  // never evidence. A usable current price must contain a positive amount.
  return numberOrNull(row?.current_list_price?.amount_thb);
}

export async function getPriceCoverageWorklist(db: any, limit = 100): Promise<PriceCoverageWorklist> {
  const [{ data: coverageRows, error: coverageError }, { data: modelRows, error: modelError }, { data: trimRows, error: trimError }, { data: brandRows, error: brandError }] = await Promise.all([
    db.from("registration_analytics_coverage")
      .select("period,total_registrations,mapped_registrations,mapped_unit_pct")
      .order("period", { ascending: true }).limit(240),
    db.from("current_vehicle_models")
      .select("canonical_id,tdr_model_id,brand_id,name_en,name_th,status,payload")
      .limit(1000),
    db.from("current_market_trims")
      .select("canonical_id,model_id,current_list_price,status")
      .limit(1000),
    db.from("current_vehicle_brands")
      .select("canonical_id,name_en,name_th")
      .limit(500),
  ]);
  if (coverageError) throw new Error(`price worklist coverage query failed: ${coverageError.message}`);
  if (modelError) throw new Error(`price worklist model query failed: ${modelError.message}`);
  if (trimError) throw new Error(`price worklist trim query failed: ${trimError.message}`);
  if (brandError) throw new Error(`price worklist brand query failed: ${brandError.message}`);

  const coverage = coverageRows || [];
  const settled = defaultMarketPeriod(coverage as any[]) || periodKey(coverage.at(-1)?.period || "");
  const periods = coverage.map((row: any) => periodKey(row.period)).filter((value: string) => value && value <= settled).slice(-3);
  const from = periods.length ? `${periods[0]}-01` : "";
  const to = periods.length ? new Date(Date.UTC(Number(periods.at(-1)!.slice(0, 4)), Number(periods.at(-1)!.slice(5, 7)), 0)).toISOString().slice(0, 10) : "";

  let registrations: any[] = [];
  if (from && to) {
    const { data, error } = await db.from("registrations")
      .select("period,model_id,registrations")
      .gte("period", from).lte("period", to)
      .not("model_id", "is", null)
      .limit(10000);
    if (error) throw new Error(`price worklist registration query failed: ${error.message}`);
    registrations = data || [];
  }

  const unitsByTdrModel = new Map<string, number>();
  for (const row of registrations) {
    const id = String(row.model_id || "");
    if (!id) continue;
    unitsByTdrModel.set(id, (unitsByTdrModel.get(id) || 0) + Number(row.registrations || 0));
  }

  const trimsByModel = new Map<string, any[]>();
  for (const row of trimRows || []) {
    const modelId = String(row.model_id || "");
    if (!modelId) continue;
    const list = trimsByModel.get(modelId) || [];
    list.push(row);
    trimsByModel.set(modelId, list);
  }
  const brands = new Map<string, string>((brandRows || []).map((row: any): [string, string] => [
    String(row.canonical_id),
    String(row.name_en || row.name_th || row.canonical_id),
  ]));
  const oemTargets = targetCountsByModel();
  const deferred = priceCoverageDecisions();
  const canonicalModels = (modelRows || []).length;
  const modelsWithTrims = [...trimsByModel.keys()].length;
  const modelsWithoutTrims = Math.max(0, canonicalModels - modelsWithTrims);

  const rows: PriceCoverageBaseRow[] = (modelRows || []).map((model: any): PriceCoverageBaseRow => {
    const modelId = String(model.canonical_id || "");
    const modelStatus = canonicalModelLifecycle(model);
    const trims = trimsByModel.get(modelId) || [];
    const current = trims.filter((trim) => lifecycle(trim?.status) === "CURRENT");
    const historical = trims.filter((trim) => lifecycle(trim?.status) === "HISTORICAL");
    const unverified = trims.filter((trim) => lifecycle(trim?.status) === "UNVERIFIED");
    const missing = current.filter((trim) => actualCurrentPrice(trim) == null);
    const pricedTrims = current.length - missing.length;
    const deferredTrims = missing.filter((trim) => deferred.has(String(trim.canonical_id || ""))).length;
    const seeds = variantSeedPrices((model.payload || {}) as JsonObject);

    let blocker: PriceCoverageBlocker | null = null;
    if (modelStatus === "UNVERIFIED") blocker = "UNRESOLVED_MODEL_LIFECYCLE";
    else if (modelStatus === "CURRENT" && trims.length === 0) blocker = "NO_MARKET_TRIM";
    else if (modelStatus === "CURRENT" && (unverified.length > 0 || current.length === 0)) blocker = "UNRESOLVED_TRIM_LIFECYCLE";
    else if (modelStatus === "CURRENT" && missing.length > 0) blocker = "MISSING_LIST_PRICE";

    return {
      canonicalModelId: modelId,
      brand: brands.get(String(model.brand_id || "")) || "UNKNOWN",
      model: String(model.name_en || model.name_th || modelId),
      modelStatus,
      blocker,
      totalTrims: trims.length,
      currentTrims: current.length,
      historicalTrims: historical.length,
      unverifiedTrims: unverified.length,
      pricedTrims,
      missingTrims: missing.length,
      deferredTrims,
      actionableMissingTrims: Math.max(0, missing.length - deferredTrims),
      registrations3m: Number(unitsByTdrModel.get(String(model.tdr_model_id || "")) || 0),
      seedMinThb: seeds.length ? Math.min(...seeds) : null,
      seedMaxThb: seeds.length ? Math.max(...seeds) : null,
      seedHintCount: seeds.length,
      oemTargetCount: oemTargets.get(modelId) || 0,
    };
  });

  // HISTORICAL models are resolved as outside today's retail-price surface.
  // UNVERIFIED models remain in the denominator so unresolved lifecycle work
  // can never make price coverage look artificially complete.
  const retailRows = rows.filter((row) => row.modelStatus !== "HISTORICAL");
  const mappedRegistrations3m = retailRows.reduce((sum, row) => sum + row.registrations3m, 0);
  const ready = retailRows.filter((row) => row.modelStatus === "CURRENT"
    && row.currentTrims > 0
    && row.unverifiedTrims === 0
    && row.missingTrims === 0);
  const readyRegistrations3m = ready.reduce((sum, row) => sum + row.registrations3m, 0);
  const readyModels = ready.length;
  const retailRelevantModels = retailRows.length;
  const currentModels = rows.filter((row) => row.modelStatus === "CURRENT").length;
  const historicalModels = rows.filter((row) => row.modelStatus === "HISTORICAL").length;
  const unverifiedModels = rows.filter((row) => row.modelStatus === "UNVERIFIED").length;
  const modelCoveragePct = retailRelevantModels ? Math.round(1000 * readyModels / retailRelevantModels) / 10 : 0;
  const registrationCoveragePct3m = mappedRegistrations3m ? Math.round(10000 * readyRegistrations3m / mappedRegistrations3m) / 100 : 0;

  const items: PriceCoverageWorkItem[] = retailRows
    .filter((row): row is PriceCoverageBaseRow & { blocker: PriceCoverageBlocker } => Boolean(row.blocker))
    .sort((a, b) => b.registrations3m - a.registrations3m
      || b.unverifiedTrims - a.unverifiedTrims
      || b.actionableMissingTrims - a.actionableMissingTrims
      || `${a.brand} ${a.model}`.localeCompare(`${b.brand} ${b.model}`))
    .slice(0, Math.max(1, Math.min(limit, 321)))
    .map((row): PriceCoverageWorkItem => ({
      ...row,
      registrationSharePct: mappedRegistrations3m ? Math.round(10000 * row.registrations3m / mappedRegistrations3m) / 100 : 0,
    }));

  return {
    periods,
    canonicalModels,
    retailRelevantModels,
    currentModels,
    historicalModels,
    unverifiedModels,
    modelsWithTrims,
    modelsWithoutTrims,
    readyModels,
    modelCoveragePct,
    mappedRegistrations3m,
    readyRegistrations3m,
    registrationCoveragePct3m,
    items,
  };
}
