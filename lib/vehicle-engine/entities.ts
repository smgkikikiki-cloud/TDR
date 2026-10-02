/**
 * The facet resolution chain and the catalog rules that need it, ported from
 * automotive/vehicle_master/vehreg/entities.py (resolve, cross_check) and the
 * resolution part of vehreg/catalog.py's Catalog.validate
 * (ENGINE_INVENTORY §4.2, §4.4).
 *
 * Rules of a single row (Model.validate, Variant.validate, MarketTrim.validate,
 * the loader's required fields) are CHECK constraints on the master tables
 * (migration_v59); they are not repeated here. What stays in TypeScript is the
 * part that only exists once the four layers are merged.
 *
 * Inputs are the stored master payloads (`asdict(...)` shapes).
 */
import {
  checkBodySegment, checkOrigin, checkPowertrain, checkRegistration, isElectrified,
  isLocallyAssembled, isPlugIn, marketPositionForPrice, marketPowertrain, normalizeCountry,
  parseFacet, powertrainGroup, truthy,
} from "./taxonomy.ts";

type Row = Record<string, any>;

const LOCKED_AT_MODEL = new Set(["body_type", "cab_type"]);
const RESOLUTION_CHAIN = ["variant", "generation", "model", "brand"] as const;

/** entities._is_set */
function isSet(value: unknown): boolean {
  return !(value === null || value === undefined || value === "" || value === "UNKNOWN");
}

function overrides(row: Row): Row {
  return row.overrides && typeof row.overrides === "object" ? row.overrides : {};
}

export function brandFacets(brand: Row): Row {
  return {
    brand: brand.name_en,
    brand_segment: brand.brand_segment,
    oem_group: brand.oem_group,
    brand_origin: normalizeCountry(brand.brand_origin),
    ...overrides(brand),
  };
}

export function modelFacets(model: Row): Row {
  return {
    model: model.name_en,
    nameplate: model.nameplate || model.name_en,
    body_type: model.body_type,
    cab_type: model.cab_type,
    registration_type: model.registration_type,
    market_scope: model.market_scope,
    ...overrides(model),
  };
}

export function generationFacets(generation: Row): Row {
  const out: Row = {
    generation: generation.code || String(generation.id).split(".").at(-1),
    segment: generation.segment,
  };
  if (truthy(generation.seats)) out.seats = generation.seats;
  return { ...out, ...overrides(generation) };
}

export function variantFacets(variant: Row): Row {
  const out: Row = {
    variant: variant.name,
    powertrain: variant.powertrain,
    drivetrain: variant.drivetrain,
    price_thb: variant.price_thb ?? null,
    market_position: marketPositionForPrice(variant.price_thb ?? null),
    import_type: variant.import_type,
    origin_country: normalizeCountry(variant.origin_country),
  };
  if (truthy(variant.price_min_thb)) out.price_min_thb = variant.price_min_thb;
  if (truthy(variant.price_max_thb)) out.price_max_thb = variant.price_max_thb;
  if (truthy(variant.engine_cc)) out.engine_cc = variant.engine_cc;
  if (truthy(variant.battery_kwh)) out.battery_kwh = variant.battery_kwh;
  return { ...out, ...overrides(variant) };
}

export type ResolvedVehicle = { variantId: string; year: number; facets: Row; provenance: Record<string, string> };

/** entities.resolve: first layer (most specific first) asserting a facet wins. */
export function resolve(brand: Row, model: Row, generation: Row, variant: Row, year: number): ResolvedVehicle {
  const layers: Record<(typeof RESOLUTION_CHAIN)[number], Row> = {
    variant: Object.fromEntries(Object.entries(variantFacets(variant)).filter(([k]) => !LOCKED_AT_MODEL.has(k))),
    generation: generationFacets(generation),
    model: modelFacets(model),
    brand: brandFacets(brand),
  };
  const facets: Row = {};
  const provenance: Record<string, string> = {};
  for (const layer of RESOLUTION_CHAIN) {
    for (const [key, value] of Object.entries(layers[layer])) {
      if (key in facets) continue;
      if (isSet(value)) {
        facets[key] = value;
        provenance[key] = layer;
      }
    }
  }
  const pt = facets.powertrain ?? "UNKNOWN";
  facets.powertrain_group = powertrainGroup(pt);
  facets.market_powertrain = marketPowertrain(pt);
  facets.is_electrified = isElectrified(pt);
  facets.is_plug_in = isPlugIn(pt);
  facets.market_position ??= "UNKNOWN";
  facets.segment ??= "UNKNOWN";
  facets.body_type ??= "OTHER";
  facets.cab_type ??= "NOT_APPLICABLE";
  facets.import_type ??= "UNKNOWN";
  facets.origin_country ??= "UNKNOWN";
  facets.market_scope ??= "UNKNOWN";
  facets.is_locally_assembled = isLocallyAssembled(facets.import_type, facets.origin_country);
  for (const derived of ["powertrain_group", "is_electrified", "is_plug_in", "is_locally_assembled"]) {
    provenance[derived] = "derived";
  }
  return { variantId: String(variant.id), year, facets, provenance };
}

/** entities.cross_check: rules that only make sense once the layers are combined. */
export function crossCheck(resolved: ResolvedVehicle): string[] {
  const f = resolved.facets;
  const body = parseFacet("BodyType", f.body_type);
  const cab = parseFacet("CabType", f.cab_type);
  const problems = [
    ...checkBodySegment(body, cab, f.segment),
    ...checkPowertrain(f.powertrain ?? "UNKNOWN", f.battery_kwh ?? null, f.engine_cc ?? null),
    ...checkOrigin(f.import_type, f.origin_country),
    ...checkRegistration(body, cab, f.registration_type),
  ];
  return problems.map((p) => `${resolved.variantId}@${resolved.year}: ${p}`);
}

export type CatalogRows = { brands: Row[]; models: Row[]; generations: Row[]; variants: Row[] };

/**
 * The resolution part of Catalog.validate: cross_check every resolved Variant,
 * skipping variants of declared-incomplete models and declared-incomplete
 * variants. Iterates variants in the given order (Python: load order).
 */
export function validateCatalogResolution(rows: CatalogRows, year: number): string[] {
  const brands = new Map(rows.brands.map((b) => [String(b.id), b]));
  const models = new Map(rows.models.map((m) => [String(m.id), m]));
  const generations = new Map(rows.generations.map((g) => [String(g.id), g]));
  const problems: string[] = [];
  for (const variant of rows.variants) {
    const generation = generations.get(String(variant.generation_id));
    const model = generation ? models.get(String(generation.model_id)) : undefined;
    const brand = model ? brands.get(String(model.brand_id)) : undefined;
    if (!generation || !model || !brand) {
      problems.push(`variant ${variant.id}: parent chain is incomplete`);
      continue;
    }
    if (truthy(model.incomplete) || truthy(variant.incomplete)) continue;
    problems.push(...crossCheck(resolve(brand, model, generation, variant, year)));
  }
  return problems;
}
