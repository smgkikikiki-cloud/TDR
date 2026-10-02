/**
 * Served (computed) values of the current_* views, recomputed from master rows
 * at a pinned as_of (ENGINE_INVENTORY §5.2–§5.5). Composition of the ported
 * rules in ./pricing.ts, ./specs.ts and ./lifecycle.ts, in the shape
 * tdr_bridge/release.py + lifecycle.py publish.
 *
 * Phase 0 does not write these: the master stores them as served
 * (`served_as_of`) and nothing recomputes them on read. This is the rule a
 * later write path recomputes them with, and what the step 4 parity checks
 * compare against Python's own output and against production's stored values.
 */
import type { SpecFieldDefinition } from "../spec-field-registry.ts";
import { campaignQuote, currentListPrice, PRICE_FIELDS, recordsFor } from "./pricing.ts";
import { resolvedFacts } from "./specs.ts";
import {
  currentGeneration, type LifecycleInputs, modelDerivedPayload, modelServedStatus, priceEligibleTrims,
  retailPriceBand, trimServedStatus,
} from "./lifecycle.ts";

type Row = Record<string, any>;

export type MasterRows = {
  models: Row[];          // vehicle_models rows (payload = served model payload)
  generations: Row[];     // payload shape: id, model_id, code, segment, seats, launched, ended
  variants: Row[];        // payload shape (asdict(Variant))
  trims: Row[];           // vehicle_trims rows (catalog_payload null for overlay trims)
  prices: Row[];          // PriceRecord dicts, retracted rows included
  campaigns: Row[];       // to_jsonable(Campaign)
  facts: Row[];           // SpecFact dicts, the whole fact store
  eco: Row[];             // ECOStickerSpec dicts
  lifecycle: LifecycleInputs;
  registry: ReadonlyMap<string, SpecFieldDefinition>;
};

const PRICE_TEXT_DEFAULTS = new Set(["source", "source_ref", "source_document_id", "notes", "retraction_reason", "reviewed_by"]);

/** to_jsonable(PriceRecord): the 16 PriceRecord fields in order, defaults filled, record_id dropped. */
export const priceRecord = (row: Row): Row =>
  Object.fromEntries(PRICE_FIELDS.map((k) => [k, row[k] ?? (PRICE_TEXT_DEFAULTS.has(k) ? "" : null)]));

export type ServedTrim = {
  status: string;
  current_list_price: Row | null;
  campaign_quote: Row;
  price_history: Row[];
  comparable_specs: Row[];
  ecosticker_evidence: Row | null;
};

export function recomputeTrim(trim: Row, rows: MasterRows, asOf: string, cache = indexes(rows)): ServedTrim {
  const model = cache.models.get(trim.model_id);
  const generation = cache.generations.get(trim.generation_id) || null;
  const lifecycle = trimServedStatus(trim, modelServedStatus(model?.payload || {}), generation, rows.lifecycle, asOf);
  if (!trim.catalog_payload) {
    // Overlay/fragment-only trim (§4.5, §9.5): no prices, no facts.
    return { status: lifecycle.status, current_list_price: null, campaign_quote: {}, price_history: [],
      comparable_specs: [], ecosticker_evidence: null };
  }
  const current = currentListPrice(rows.prices, trim.canonical_id, asOf);
  return {
    status: lifecycle.status,
    current_list_price: current ? priceRecord(current) : null,
    campaign_quote: campaignQuote(rows.prices, cache.campaigns, trim.canonical_id, asOf),
    price_history: recordsFor(rows.prices, trim.canonical_id).map(priceRecord),
    comparable_specs: resolvedFacts(rows.facts, rows.registry, trim.canonical_id, asOf),
    ecosticker_evidence: cache.eco.get(trim.canonical_id) || null,
  };
}

export type ServedModel = {
  generation_id: string | null;
  segment: string;
  status: string;
  retail_price_min: number | null;
  retail_price_max: number | null;
  payload: Row;
};

export function recomputeModel(model: Row, rows: MasterRows, asOf: string, cache = indexes(rows)): ServedModel {
  const current = currentGeneration(cache.generationList, model.canonical_id, asOf);
  const eligible = priceEligibleTrims(model, cache.generationList, cache.catalogTrims, rows.lifecycle, asOf);
  const band = retailPriceBand(eligible, rows.prices, asOf);
  return {
    generation_id: current ? current.id : null,
    segment: current ? current.segment : "UNKNOWN",
    status: modelServedStatus(model.payload || {}),
    retail_price_min: band.min,
    retail_price_max: band.max,
    payload: modelDerivedPayload(model, cache.generationList, rows.variants, asOf, model.payload || {}),
  };
}

export function indexes(rows: MasterRows) {
  return {
    models: new Map(rows.models.map((m) => [m.canonical_id, m])),
    generationList: rows.generations,
    generations: new Map(rows.generations.map((g) => [g.id, g])),
    catalogTrims: rows.trims.filter((t) => t.catalog_payload),
    campaigns: new Map(rows.campaigns.map((c) => [c.id, c])),
    eco: new Map(rows.eco.map((e) => [e.trim_id, e])),
  };
}
