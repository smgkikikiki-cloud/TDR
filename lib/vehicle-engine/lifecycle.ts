/**
 * Served lifecycle and model values, ported from
 * automotive/vehicle_master/tdr_bridge/lifecycle.py (apply_retail_lifecycle),
 * vehreg/retail_scope.py (active generations, price eligibility) and
 * tdr_bridge/release.py (ReleaseBuilder.build's model/trim fields).
 * ENGINE_INVENTORY §5.2, §5.3.
 *
 * Every function takes `asOf` explicitly. Phase 0 keeps these values frozen in
 * the master exactly as served (`served_as_of`); recomputing them is only ever
 * done with that pinned date, never with "today" (ENGINE_INVENTORY §9.1).
 */
import { currentListAmount } from "./pricing.ts";

type Row = Record<string, any>;

export type LifecycleInputs = {
  /** model_id -> approved CURRENT trim ids (vehicle_current_retail_sets). */
  approved: ReadonlyMap<string, ReadonlySet<string>>;
  /** trim_id -> HUMAN decision row (vehicle_trim_lifecycle_decisions). */
  decisions: ReadonlyMap<string, Row>;
  /** model ids flagged UNDER_MAINTENANCE (vehicle_model_operational_states). */
  maintenance: ReadonlySet<string>;
};

const ALLOWED = new Set(["CURRENT", "HISTORICAL", "UNVERIFIED"]);

/** lifecycle._status */
function status(value: unknown, fallback = "CURRENT"): string {
  const normalized = String(value || fallback).trim().toUpperCase();
  return ALLOWED.has(normalized) ? normalized : fallback;
}

/** Served model status: HISTORICAL if the catalog says so, else CURRENT (never UNVERIFIED, §9.4). */
export function modelServedStatus(modelPayload: Row): "CURRENT" | "HISTORICAL" {
  return status(modelPayload?.retail_status) === "HISTORICAL" ? "HISTORICAL" : "CURRENT";
}

function onOrBefore(value: string | null | undefined, asOf: string): boolean {
  return !value || value <= asOf;
}
function after(value: string | null | undefined, asOf: string): boolean {
  return !value || value > asOf;
}

/** retail_scope.active_generations_of, sorted by (launched or "", id). */
export function activeGenerations(generations: Row[], modelId: string, asOf: string): Row[] {
  return generations
    .filter((g) => g.model_id === modelId && onOrBefore(g.launched, asOf) && after(g.ended, asOf))
    .sort((a, b) => cmp([a.launched || "", a.id], [b.launched || "", b.id]));
}

function cmp(a: string[], b: string[]): number {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

/** ReleaseBuilder: newest active generation (launched desc, id desc), else newest of all. */
export function currentGeneration(generations: Row[], modelId: string, asOf: string): Row | null {
  const newestFirst = (rows: Row[]) => [...rows].sort((a, b) => cmp([b.launched || "", b.id], [a.launched || "", a.id]));
  const active = newestFirst(activeGenerations(generations, modelId, asOf));
  if (active.length) return active[0];
  const all = newestFirst(generations.filter((g) => g.model_id === modelId));
  return all[0] || null;
}

/** lifecycle.apply_retail_lifecycle for one trim. */
export function trimServedStatus(trim: Row, modelStatus: string, generation: Row | null, inputs: LifecycleInputs,
  asOf: string): { status: string; review: Row | null } {
  const ended = String(generation?.ended || "").trim();
  const generationHistorical = Boolean(ended) && ended <= asOf;
  const approved = inputs.approved.get(trim.model_id);
  const decision = inputs.decisions.get(trim.canonical_id);
  const review = decision
    ? { reviewer: decision.reviewer, reviewed_at: decision.reviewed_at, source_ref: decision.source_ref, notes: decision.notes }
    : null;
  if (modelStatus === "HISTORICAL" || generationHistorical) return { status: "HISTORICAL", review: null };
  if (approved) {
    if (approved.has(trim.canonical_id)) return { status: "CURRENT", review: null };
    if (decision && decision.status === "HISTORICAL") return { status: "HISTORICAL", review };
    return { status: "UNVERIFIED", review: null };
  }
  if (decision) return { status: status(decision.status), review };
  return { status: "CURRENT", review: null };
}

/**
 * retail_scope.scoped_siblings_by_model for one model: the base-catalog trims
 * that are price-eligible on asOf.
 */
export function priceEligibleTrims(model: Row, generations: Row[], catalogTrims: Row[], inputs: LifecycleInputs,
  asOf: string): Row[] {
  if (inputs.maintenance.has(model.canonical_id)) return [];
  if (model.payload?.retail_status === "HISTORICAL") return [];
  const active = activeGenerations(generations, model.canonical_id, asOf);
  if (!active.length) return [];
  const trims = active.flatMap((g) => catalogTrims.filter((t) => t.generation_id === g.id));
  const approved = inputs.approved.get(model.canonical_id);
  if (approved) return trims.filter((t) => approved.has(t.canonical_id));
  return trims.filter((t) => inputs.decisions.get(t.canonical_id)?.status !== "HISTORICAL");
}

/** ReleaseBuilder: min/max current LIST amount over the price-eligible trims. */
export function retailPriceBand(eligible: Row[], prices: Row[], asOf: string): { min: number | null; max: number | null } {
  const amounts = eligible.map((t) => currentListAmount(prices, t.canonical_id, asOf)).filter((n): n is number => n !== null);
  return amounts.length ? { min: Math.min(...amounts), max: Math.max(...amounts) } : { min: null, max: null };
}

/**
 * The model payload fields ReleaseBuilder derives from the catalog. Editorial
 * fallbacks (production_type/production_country when no variant states one,
 * launch_year when the generation has no launch date) come from the
 * release-time crosswalk, which the master stores as served; `stored` supplies
 * them.
 */
export function modelDerivedPayload(model: Row, generations: Row[], variants: Row[], asOf: string, stored: Row): Row {
  const current = currentGeneration(generations, model.canonical_id, asOf);
  const generationIds = new Set(generations.filter((g) => g.model_id === model.canonical_id).map((g) => g.id));
  const modelVariants = variants.filter((v) => generationIds.has(v.generation_id));
  const sortedSet = (values: string[]) => [...new Set(values)].sort();
  const powertrains = sortedSet(modelVariants.map((v) => v.powertrain).filter((p) => p !== "UNKNOWN"));
  const importTypes = sortedSet(modelVariants.map((v) => v.import_type).filter((p) => p !== "UNKNOWN"));
  const origins = sortedSet(modelVariants.map((v) => v.origin_country).filter((p) => p !== "" && p !== "UNKNOWN" && p !== null && p !== undefined));
  return {
    generation: current ? current.code : null,
    seats: current ? current.seats ?? null : null,
    powertrains,
    production_type: importTypes.length === 1 ? importTypes[0] : importTypes.length ? "MIXED" : stored.production_type ?? null,
    production_country: origins.length === 1 ? origins[0] : origins.length ? "MIXED" : stored.production_country ?? null,
    launch_year: current && current.launched ? Number(String(current.launched).slice(0, 4)) : stored.launch_year ?? null,
  };
}
