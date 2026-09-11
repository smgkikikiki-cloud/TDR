export type MarketPriceBand = "ENTRY" | "VOLUME" | "UPPER" | "LUXURY" | "MIXED" | "UNKNOWN";

export const MARKET_PRICE_BANDS: readonly MarketPriceBand[] = ["ENTRY", "VOLUME", "UPPER", "LUXURY"];
export const MARKET_PRICE_MIN_COVERAGE_PCT = 80;

type PriceRow = {
  trim_id: string | null;
  amount_thb: number | string | null;
  price_type: string | null;
  effective_from: string | null;
  effective_to: string | null;
  observed_at: string | null;
  payload: Record<string, unknown> | null;
};
type TrimRow = { canonical_id: string | null; model_id: string | null; generation_id: string | null };
type GenerationRow = { canonical_id: string | null; launched: string | null; ended: string | null };
type TrimState = { trimId: string; generationId: string | null };

export type MarketPriceState = {
  releaseId: string;
  trimsByModel: Map<string, TrimState[]>;
  generations: Map<string, { launched: string | null; ended: string | null }>;
  listPricesByTrim: Map<string, PriceRow[]>;
};

let cache: { releaseId: string; promise: Promise<MarketPriceState> } | null = null;

function dateOnly(value: unknown): string | null {
  const text = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : null;
}

function monthEnd(period: string): string | null {
  const match = /^(\d{4})-(\d{2})(?:-\d{2})?$/.exec(String(period || ""));
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

export function marketPriceBandForAmount(amount: number | null | undefined): MarketPriceBand {
  if (amount == null || !Number.isFinite(Number(amount)) || Number(amount) < 0) return "UNKNOWN";
  const value = Number(amount);
  if (value < 500_000) return "ENTRY";
  if (value < 1_000_000) return "VOLUME";
  if (value < 1_800_000) return "UPPER";
  return "LUXURY";
}

function generationActiveOn(state: MarketPriceState, generationId: string | null, day: string): boolean {
  if (!generationId) return true;
  const generation = state.generations.get(generationId);
  if (!generation) return true;
  if (generation.launched && generation.launched > day) return false;
  // Mirrors canonical release semantics: ended <= as_of means discontinued.
  if (generation.ended && generation.ended <= day) return false;
  return true;
}

export function resolveListPriceOn(rows: PriceRow[], day: string): number | null {
  const candidates = rows.filter((row) => {
    if (String(row.price_type || "").toUpperCase() !== "LIST_PRICE") return false;
    // Retraction means the canonical row was wrong, not merely ended later.
    if (row.payload && row.payload.retracted_at) return false;
    const start = dateOnly(row.effective_from) || dateOnly(row.observed_at);
    if (!start || start > day) return false;
    const end = dateOnly(row.effective_to);
    return !end || end >= day;
  });
  if (!candidates.length) return null;
  const latestStart = candidates.reduce((latest, row) => {
    const start = dateOnly(row.effective_from) || dateOnly(row.observed_at) || "0001-01-01";
    return start > latest ? start : latest;
  }, "0001-01-01");
  const latest = candidates.filter((row) => (dateOnly(row.effective_from) || dateOnly(row.observed_at)) === latestStart);
  const amounts = [...new Set(latest.map((row) => Number(row.amount_thb)).filter((value) => Number.isFinite(value) && value > 0))];
  return amounts.length === 1 ? amounts[0] : null;
}

export function resolveModelPriceBand(state: MarketPriceState | null, modelId: string | null, period: string): MarketPriceBand {
  if (!state || !modelId) return "UNKNOWN";
  const day = monthEnd(period);
  if (!day) return "UNKNOWN";
  const activeTrims = (state.trimsByModel.get(modelId) || []).filter((trim) => generationActiveOn(state, trim.generationId, day));
  if (!activeTrims.length) return "UNKNOWN";

  const bands = new Set<MarketPriceBand>();
  for (const trim of activeTrims) {
    const amount = resolveListPriceOn(state.listPricesByTrim.get(trim.trimId) || [], day);
    const band = marketPriceBandForAmount(amount);
    // A model-grain registration cannot be assigned to a price cohort unless
    // every active canonical trim has a verified list price for that month.
    if (band === "UNKNOWN") return "UNKNOWN";
    bands.add(band);
  }
  if (bands.size === 1) return [...bands][0];
  return "MIXED";
}

export async function getActiveMarketPriceState(db: any): Promise<MarketPriceState | null> {
  const { data: stateRow, error: stateError } = await db
    .from("canonical_vehicle_state")
    .select("active_release_id")
    .limit(1)
    .maybeSingle();
  if (stateError) throw new Error(`canonical price state query failed: ${stateError.message}`);
  const releaseId = String(stateRow?.active_release_id || "");
  if (!releaseId) return null;
  if (cache?.releaseId === releaseId) return cache.promise;

  const promise = (async () => {
    const [trimResult, generationResult, priceResult] = await Promise.all([
      db.from("current_market_trims").select("canonical_id,model_id,generation_id").limit(1000),
      db.from("current_vehicle_generations").select("canonical_id,launched,ended").limit(1000),
      db.from("canonical_price_projection")
        .select("trim_id,amount_thb,price_type,effective_from,effective_to,observed_at,payload")
        .eq("release_id", releaseId)
        .limit(5000),
    ]);
    if (trimResult.error) throw new Error(`canonical trim price map query failed: ${trimResult.error.message}`);
    if (generationResult.error) throw new Error(`canonical generation price map query failed: ${generationResult.error.message}`);
    if (priceResult.error) throw new Error(`canonical price ledger query failed: ${priceResult.error.message}`);

    const trimsByModel = new Map<string, TrimState[]>();
    for (const row of (trimResult.data || []) as TrimRow[]) {
      if (!row.canonical_id || !row.model_id) continue;
      const key = String(row.model_id);
      const list = trimsByModel.get(key) || [];
      list.push({ trimId: String(row.canonical_id), generationId: row.generation_id ? String(row.generation_id) : null });
      trimsByModel.set(key, list);
    }
    const generations = new Map<string, { launched: string | null; ended: string | null }>();
    for (const row of (generationResult.data || []) as GenerationRow[]) {
      if (!row.canonical_id) continue;
      generations.set(String(row.canonical_id), { launched: dateOnly(row.launched), ended: dateOnly(row.ended) });
    }
    const listPricesByTrim = new Map<string, PriceRow[]>();
    for (const row of (priceResult.data || []) as PriceRow[]) {
      if (!row.trim_id || String(row.price_type || "").toUpperCase() !== "LIST_PRICE") continue;
      const key = String(row.trim_id);
      const list = listPricesByTrim.get(key) || [];
      list.push(row);
      listPricesByTrim.set(key, list);
    }
    return { releaseId, trimsByModel, generations, listPricesByTrim };
  })();
  cache = { releaseId, promise };
  return promise;
}

export function priceStateModelCoverage(state: MarketPriceState | null, period: string) {
  if (!state) return { pricedModels: 0, mixedModels: 0, modelsWithTrims: 0 };
  let pricedModels = 0;
  let mixedModels = 0;
  for (const modelId of state.trimsByModel.keys()) {
    const band = resolveModelPriceBand(state, modelId, period);
    if (MARKET_PRICE_BANDS.includes(band)) pricedModels += 1;
    else if (band === "MIXED") mixedModels += 1;
  }
  return { pricedModels, mixedModels, modelsWithTrims: state.trimsByModel.size };
}
