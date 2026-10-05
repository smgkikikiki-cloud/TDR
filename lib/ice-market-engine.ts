/**
 * Market Track M4 -- the Ice-backed market engine.
 *
 * Pure, dimension-aware aggregation over Ice panel rows (migration_v62) and the
 * Ice <-> TDR crosswalk (migration_v63), per docs/vehicle-db/VEHICLE_DB_V3.md §14.3.
 * No Supabase import here and no network access -- `lib/ice-market-data.ts` is the
 * thin I/O wrapper that fetches rows and calls these functions, exactly the split
 * between `lib/registration-market.ts` (pure) and `lib/registration-analytics.ts`
 * (I/O) that the legacy engine already uses.
 *
 * This module never reads the legacy registration engine's tables or types. It
 * reuses only genuinely engine-agnostic pieces from lib/registration-market.ts:
 * the period/window helpers (shiftReportPeriod, resolveMarketWindow, …) do pure
 * integer year*12+month arithmetic on a "YYYY-MM"/"YYYY-MM-DD" string and never
 * construct a real calendar Date, so they are correct unchanged on Ice's Buddhist
 * "YYYY-MM" periods too (the year number is just a larger integer); compareMarketSliceRows
 * is a pure diff over two already-built MarketSliceRow[] arrays with no mapping-status
 * assumptions baked in, so reusing it exactly carries no legacy semantics.
 *
 * `sliceMarketFacts` (the legacy per-fact slicer) is deliberately NOT reused: its
 * "usable" gate hides a row by default unless it is `canonically_mapped`, which is
 * exactly backwards for Ice brand/model (§14.3: Ice is authoritative for both --
 * units must never be dropped just because no TDR link exists) and does not model
 * the "ไม่ระบุ" bucket segment/body_type need (a real, counted, visible row -- not
 * an excluded one). The slicers below implement §14.3's inclusion rules directly.
 */
// Relative (not "@/lib/...") imports here on purpose: this module is designed
// to be runnable both inside the Next.js app and directly via
// `node --experimental-strip-types` (scripts/check-ice-market-engine.ts),
// which cannot resolve the "@/" path alias -- only plain relative specifiers.
import { compareMarketSliceRows, type MarketSliceRow } from "./registration-market.ts";
import type { PublicMarket } from "./public-market.ts";

// ---------------------------------------------------------------------------
// Raw per-panel row shapes (migration_v62/v63 columns, one type per table --
// CLAUDE.md rule 1: never mix panels in one request/export, so these are never
// joined into one combined "fact" row the way the legacy engine's single
// `registrations` source allowed).
// ---------------------------------------------------------------------------

export type IceRegProvinceRow = {
  period: string; province: string; reg_type: string; brand: string;
  fuel_group: string; reg_count: number;
};

export type IceRegTrendRow = {
  period: string; province: string; reg_type: string; brand: string;
  model_group_id: string; model_name: string; reg_count: number;
};

export type IcePowertrainCertainty = "exact" | "family" | "range";

export type IceRegPowertrainRow = {
  period: string; province: string; reg_type: string; brand: string;
  model_group_id: string; model_name: string; fuel_group: string;
  reg_est: number | null; reg_min: number | null; reg_max: number | null;
  certainty: IcePowertrainCertainty;
};

export type IceRimProvinceRow = {
  period: string; province: string; reg_type: string; brand: string;
  rim_bucket: string; reg_est: number | null;
};

export type IceTyreProvinceRow = {
  period: string; province: string; reg_type: string; brand: string;
  tyre_size: string; rim_inch: number | null; reg_est: number | null;
};

export type IceTyreCoverageRow = {
  period: string; province: string; reg_type: string; brand: string;
  reg_total: number | null; reg_tyre_known: number | null;
};

export type IceCrosswalkStatus = "AUTO" | "APPROVED" | "PROPOSED" | "REJECTED";

export type IceCrosswalkLink = {
  model_group_id: string;
  canonical_model_id: string | null;
  status: IceCrosswalkStatus;
};

export type VehicleModelDim = {
  canonical_id: string;
  segment: string | null;
  body_type: string | null;
};

export type IceModelGroupRedirectRow = {
  old_model_group_id: string;
  new_model_group_id: string;
};

// ---------------------------------------------------------------------------
// Filters -- an Ice-specific type, not a modification of the frozen
// MarketSliceFilters (§15.2: new data needs are new optional additions at the
// *contract* boundary; this engine's own internal filter shape is free to
// differ, since `province` has no equivalent in the legacy contract at all --
// §14.3: "Units, province, reg type, period: Ice only, as delivered").
// ---------------------------------------------------------------------------

export type IceMarketFilters = {
  provinces?: string[];
  registrationTypes?: string[];
  brands?: string[];
  modelGroupIds?: string[];
};

/** "ไม่ระบุ" -- the TDR-segment/body_type bucket for an Ice unit with no active
 * (AUTO/APPROVED) crosswalk mapping, or whose mapped TDR models disagree (see
 * resolveModelDimensionValue). A real, counted, visible row -- never dropped. */
export const UNMAPPED_LABEL = "ไม่ระบุ";

const FAMILY_NOTE = "แบ่งระหว่างรุ่นในตระกูลโดย TDR";

function passesIceFilters(
  row: { province: string; reg_type: string; brand: string },
  filters: IceMarketFilters,
): boolean {
  return (!filters.provinces?.length || filters.provinces.includes(row.province))
    && (!filters.registrationTypes?.length || filters.registrationTypes.includes(row.reg_type))
    && (!filters.brands?.length || filters.brands.includes(row.brand));
}

function passesModelGroupFilter(row: { model_group_id: string }, filters: IceMarketFilters): boolean {
  return !filters.modelGroupIds?.length || filters.modelGroupIds.includes(row.model_group_id);
}

// ---------------------------------------------------------------------------
// Dimension/filter support matrix (PR #189 review round 2, fix 4): every
// IceMarketFilters field must be honored exactly wherever the source panel
// backing a dimension actually carries that column, and refused loudly
// everywhere it does not -- never silently ignored, which would return a
// broader-than-requested slice that still looks like a valid, narrowed one.
//
// model_group_id exists on ice_reg_trend and ice_reg_powertrain (so "model",
// "segment", "body_type" and "powertrain" all honor modelGroupIds below) but
// NOT on ice_reg_province (so "brand" and "registration_type" cannot).
// province/reg_type/brand exist on every panel, so those three filters are
// always supported regardless of dimension.
// ---------------------------------------------------------------------------

export type IceMarketDimension = "brand" | "model" | "segment" | "body_type" | "powertrain" | "registration_type";

export function isIceMarketDimension(value: string): value is IceMarketDimension {
  return value === "brand" || value === "model" || value === "segment"
    || value === "body_type" || value === "powertrain" || value === "registration_type";
}

const MODEL_GROUP_ID_DIMENSIONS: ReadonlySet<IceMarketDimension> = new Set(["model", "segment", "body_type", "powertrain"]);

export class IceUnsupportedFilterError extends Error {
  constructor(filterName: string, dimension: IceMarketDimension) {
    super(
      `the "${filterName}" filter has no matching column on the Ice panel backing the `
      + `"${dimension}" dimension (ice_reg_province has no model_group_id) -- refused rather `
      + "than silently returning a broader slice than requested.",
    );
  }
}

/** Throws IceUnsupportedFilterError rather than letting an unsupported filter
 * be silently ignored. Call this before slicing with any (dimension, filters)
 * pair reached from outside this module (lib/ice-market-data.ts's
 * getIceMarketSlice) -- the slicers below assume it has already been checked. */
export function assertIceFiltersSupported(dimension: IceMarketDimension, filters: IceMarketFilters): void {
  if (filters.modelGroupIds?.length && !MODEL_GROUP_ID_DIMENSIONS.has(dimension)) {
    throw new IceUnsupportedFilterError("modelGroupIds", dimension);
  }
}

function rankedSliceRows(
  grouped: Map<string, { label: string; units: number }>,
  limit: number,
  coverage: { raw: number; mapped: number },
): MarketSliceRow[] {
  const ranked = [...grouped.entries()]
    .map(([key, row]) => ({ key, ...row }))
    .sort((a, b) => b.units - a.units || a.key.localeCompare(b.key));
  const boundedLimit = Math.min(Math.max(Math.trunc(limit), 1), 500);
  const total = ranked.reduce((sum, row) => sum + row.units, 0);
  const coveragePct = coverage.raw ? Math.round((1000 * coverage.mapped) / coverage.raw) / 10 : 0;

  return ranked.slice(0, boundedLimit).map((row, index) => ({
    entity_key: row.key,
    entity_label: row.label,
    registrations: row.units,
    market_total: total,
    market_share_pct: total ? Math.round((10000 * row.units) / total) / 100 : 0,
    market_rank: index + 1,
    window_raw_units: coverage.raw,
    window_mapped_units: coverage.mapped,
    window_mapping_coverage_pct: coveragePct,
  }));
}

// ---------------------------------------------------------------------------
// Brand / registration_type (ice_reg_province -- exact units, always fully
// "known": Ice is authoritative for brand and reg_type, so coverage is always
// 100% and nothing is ever excluded by a mapping gate, only by an explicit filter.
// ---------------------------------------------------------------------------

export function sliceIceByBrand(
  rows: IceRegProvinceRow[], filters: IceMarketFilters = {}, limit = 100,
): MarketSliceRow[] {
  const filtered = rows.filter((row) => passesIceFilters(row, filters));
  const grouped = new Map<string, { label: string; units: number }>();
  let raw = 0;
  for (const row of filtered) {
    const units = Number(row.reg_count || 0);
    raw += units;
    const previous = grouped.get(row.brand);
    grouped.set(row.brand, { label: row.brand, units: (previous?.units || 0) + units });
  }
  return rankedSliceRows(grouped, limit, { raw, mapped: raw });
}

export function sliceIceByRegistrationType(
  rows: IceRegProvinceRow[], filters: IceMarketFilters = {}, limit = 100,
): MarketSliceRow[] {
  const filtered = rows.filter((row) => passesIceFilters(row, filters));
  const grouped = new Map<string, { label: string; units: number }>();
  let raw = 0;
  for (const row of filtered) {
    const units = Number(row.reg_count || 0);
    raw += units;
    const previous = grouped.get(row.reg_type);
    grouped.set(row.reg_type, { label: row.reg_type, units: (previous?.units || 0) + units });
  }
  return rankedSliceRows(grouped, limit, { raw, mapped: raw });
}

// ---------------------------------------------------------------------------
// Model (ice_reg_trend -- exact units). entity_key is ALWAYS the Ice
// model_group_id, mapped or not (§14.3: "Ice model_group_id is the market
// identity ... unmatched Ice groups remain visible and unlinked, never drop
// their units" -- this is a deliberate, documented divergence from the legacy
// engine's `entity_key = canonical_model_id | raw-model:...`, listed in
// SERVING_CONTRACT.md §6 as an already-expected M4/M5 difference).
// canonical_model_id is attached as new OPTIONAL metadata (§15.2) when an
// AUTO/APPROVED crosswalk link exists; PROPOSED/REJECTED links never surface
// here -- they are pending/rejected, not a confirmed mapping.
// ---------------------------------------------------------------------------

export type IceModelSliceRow = MarketSliceRow & { canonical_model_id: string | null };

function activeLinksByGroup(crosswalk: IceCrosswalkLink[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const link of crosswalk) {
    if (!link.canonical_model_id) continue;
    if (link.status !== "AUTO" && link.status !== "APPROVED") continue;
    const list = map.get(link.model_group_id) ?? [];
    list.push(link.canonical_model_id);
    map.set(link.model_group_id, list);
  }
  return map;
}

/** The single canonical_model_id for a group's model-dimension link. Many TDR
 * models may actively map to one Ice group (§14.2); for the model dimension's
 * own link we surface the first one deterministically (sorted) rather than
 * picking arbitrarily -- the *display* consequence of multiple TDR models per
 * group belongs to the segment/body_type aggregation below, not to this link. */
function primaryLinkedModel(ids: string[] | undefined): string | null {
  if (!ids || !ids.length) return null;
  return [...ids].sort()[0];
}

export function sliceIceByModel(
  rows: IceRegTrendRow[], crosswalk: IceCrosswalkLink[], filters: IceMarketFilters = {}, limit = 100,
): IceModelSliceRow[] {
  const filtered = rows.filter((row) => passesIceFilters(row, filters) && passesModelGroupFilter(row, filters));
  const links = activeLinksByGroup(crosswalk);
  const grouped = new Map<string, { label: string; units: number }>();
  let raw = 0;
  for (const row of filtered) {
    const units = Number(row.reg_count || 0);
    raw += units;
    const previous = grouped.get(row.model_group_id);
    grouped.set(row.model_group_id, {
      label: [row.brand, row.model_name].filter(Boolean).join(" "),
      units: (previous?.units || 0) + units,
    });
  }
  const base = rankedSliceRows(grouped, limit, { raw, mapped: raw });
  return base.map((row) => ({
    ...row,
    canonical_model_id: primaryLinkedModel(links.get(row.entity_key)),
  }));
}

// ---------------------------------------------------------------------------
// Segment / body_type -- TDR Vehicle DB via APPROVED/AUTO crosswalk only
// (§14.3). Units whose Ice model_group_id has no active link, or whose
// actively-linked TDR models disagree on the dimension value, go to the real,
// counted UNMAPPED_LABEL ("ไม่ระบุ") bucket -- never dropped, never guessed.
// ---------------------------------------------------------------------------

function resolveModelDimensionValue(
  modelGroupId: string,
  linksByGroup: Map<string, string[]>,
  modelById: Map<string, VehicleModelDim>,
  pick: (model: VehicleModelDim) => string | null,
): string | null {
  const ids = linksByGroup.get(modelGroupId);
  if (!ids || !ids.length) return null;
  const values = new Set(
    ids.map((id) => modelById.get(id)).filter((model): model is VehicleModelDim => Boolean(model))
      .map((model) => pick(model)),
  );
  if (values.size !== 1) return null; // no agreeing value, or disagreement among siblings -> ไม่ระบุ
  const [only] = values;
  return only ?? null;
}

function sliceIceByTdrDimension(
  rows: IceRegTrendRow[], crosswalk: IceCrosswalkLink[], models: VehicleModelDim[],
  pick: (model: VehicleModelDim) => string | null,
  filters: IceMarketFilters = {}, limit = 100,
): MarketSliceRow[] {
  const filtered = rows.filter((row) => passesIceFilters(row, filters) && passesModelGroupFilter(row, filters));
  const links = activeLinksByGroup(crosswalk);
  const modelById = new Map(models.map((model) => [model.canonical_id, model]));
  const grouped = new Map<string, { label: string; units: number }>();
  let raw = 0;
  let mapped = 0;
  for (const row of filtered) {
    const units = Number(row.reg_count || 0);
    raw += units;
    const value = resolveModelDimensionValue(row.model_group_id, links, modelById, pick);
    const key = value || UNMAPPED_LABEL;
    if (value) mapped += units;
    const previous = grouped.get(key);
    grouped.set(key, { label: key, units: (previous?.units || 0) + units });
  }
  return rankedSliceRows(grouped, limit, { raw, mapped });
}

export function sliceIceBySegment(
  rows: IceRegTrendRow[], crosswalk: IceCrosswalkLink[], models: VehicleModelDim[],
  filters: IceMarketFilters = {}, limit = 100,
): MarketSliceRow[] {
  return sliceIceByTdrDimension(rows, crosswalk, models, (model) => model.segment, filters, limit);
}

export function sliceIceByBodyType(
  rows: IceRegTrendRow[], crosswalk: IceCrosswalkLink[], models: VehicleModelDim[],
  filters: IceMarketFilters = {}, limit = 100,
): MarketSliceRow[] {
  return sliceIceByTdrDimension(rows, crosswalk, models, (model) => model.body_type, filters, limit);
}

// ---------------------------------------------------------------------------
// Powertrain (ice_reg_powertrain + fuel_group ONLY -- §14.3: never regroup
// using the Vehicle DB powertrain taxonomy, never collapse into
// ICE/MIXED/REEV/UNKNOWN, never the word "ประมาณการ").
// ---------------------------------------------------------------------------

export type ResolvedPowertrainRow = {
  value: number;
  certainty: IcePowertrainCertainty;
  reg_min: number | null;
  reg_max: number | null;
  note: string | null;
};

/** The §14.3 per-row display rule, exactly:
 *    exact  -> reg_est
 *    family -> reg_est, plus the required note
 *    range  -> expose reg_min..reg_max (value is their midpoint, used only for
 *              ranking/summation -- the range itself is the real display fact)
 * Matches vehreg/ice_package.py's `_powertrain_value` convention (M2): prefer
 * reg_est, else the min/max midpoint. */
export function resolveIcePowertrainRow(row: IceRegPowertrainRow): ResolvedPowertrainRow {
  if (row.certainty === "range") {
    const min = row.reg_min != null ? Number(row.reg_min) : 0;
    const max = row.reg_max != null ? Number(row.reg_max) : 0;
    return { value: (min + max) / 2, certainty: "range", reg_min: min, reg_max: max, note: null };
  }
  const value = row.reg_est != null ? Number(row.reg_est) : 0;
  return {
    value,
    certainty: row.certainty,
    reg_min: row.reg_min != null ? Number(row.reg_min) : null,
    reg_max: row.reg_max != null ? Number(row.reg_max) : null,
    note: row.certainty === "family" ? FAMILY_NOTE : null,
  };
}

// ---------------------------------------------------------------------------
// PR #189 review round 2, fix 1: a grouped fuel_group bucket must never
// collapse a range row's min/max into an indistinguishable "exact" number --
// that is false precision (e.g. a true 60..80 range silently reported as a
// plain registrations=70). IcePowertrainSliceRow extends the frozen
// MarketSliceRow with optional fields only (§15.2) so it remains assignable
// anywhere a MarketSliceRow is expected; `registrations` stays a single
// number for ranking/sorting/share math (the midpoint when the bucket's
// certainty is "range"), but `certainty`/`registrations_min`/
// `registrations_max`/`note` are what a consumer MUST read before displaying
// a powertrain number as if it were exact.
// ---------------------------------------------------------------------------

export type IcePowertrainSliceRow = MarketSliceRow & {
  certainty: IcePowertrainCertainty;
  registrations_min: number;
  registrations_max: number;
  note: string | null;
};

export function sliceIceByPowertrain(
  rows: IceRegPowertrainRow[], filters: IceMarketFilters = {}, limit = 100,
): IcePowertrainSliceRow[] {
  const filtered = rows.filter((row) => passesIceFilters(row, filters) && passesModelGroupFilter(row, filters));
  const grouped = new Map<string, { label: string; units: number; min: number; max: number; hasRange: boolean; hasFamily: boolean }>();
  let raw = 0;
  for (const row of filtered) {
    const resolved = resolveIcePowertrainRow(row);
    raw += resolved.value;
    const previous = grouped.get(row.fuel_group)
      ?? { label: row.fuel_group, units: 0, min: 0, max: 0, hasRange: false, hasFamily: false };
    // exact/family contribute their one number to both min and max (nothing
    // to range over); range contributes its own reg_min/reg_max -- never the
    // midpoint -- so a grouped bucket that mixes certainties still carries a
    // real, honest aggregate range rather than an average of averages.
    const isRange = resolved.certainty === "range";
    previous.units += resolved.value;
    previous.min += isRange ? (resolved.reg_min ?? resolved.value) : resolved.value;
    previous.max += isRange ? (resolved.reg_max ?? resolved.value) : resolved.value;
    if (isRange) previous.hasRange = true;
    if (resolved.certainty === "family") previous.hasFamily = true;
    grouped.set(row.fuel_group, previous);
  }
  const base = rankedSliceRows(
    new Map([...grouped].map(([key, value]) => [key, { label: value.label, units: value.units }])),
    limit, { raw, mapped: raw },
  );
  return base.map((row) => {
    const group = grouped.get(row.entity_key);
    if (!group) return { ...row, certainty: "exact", registrations_min: row.registrations as number, registrations_max: row.registrations as number, note: null };
    // A bucket is only ever reported "exact" when EVERY row that fed it was
    // exact. Any range component forces the bucket to "range" (never claim
    // exactness once any input was a range); a family component (with no
    // range) forces "family" and the required note -- never "ประมาณการ".
    const certainty: IcePowertrainCertainty = group.hasRange ? "range" : group.hasFamily ? "family" : "exact";
    return {
      ...row,
      certainty,
      registrations_min: group.min,
      registrations_max: group.max,
      note: certainty === "family" ? FAMILY_NOTE : null,
    };
  });
}

// ---------------------------------------------------------------------------
// Wheel / tyre -- "TDR Wheel & Tyre Index". Always exposes coverage. Publish
// start comes from the panel manifest's period_from, passed in by the caller
// -- never hard-coded (§14.3: never hard-code any particular calendar start
// period). See docs/WORK_STATE.md for the M2 metadata-persistence gap this
// depends on for a REAL period_from.
// ---------------------------------------------------------------------------

export type WheelTyreAvailability = { available: boolean; periodFrom: string };

export function resolveWheelTyreAvailability(periodFrom: string, period: string): WheelTyreAvailability {
  return { available: period >= periodFrom, periodFrom };
}

export type WheelTyreCoverage = { regTotal: number; regKnown: number; coveragePct: number };

export function wheelTyreCoverage(rows: IceTyreCoverageRow[], filters: IceMarketFilters = {}): WheelTyreCoverage {
  const filtered = rows.filter((row) => passesIceFilters(row, filters));
  const regTotal = filtered.reduce((sum, row) => sum + Number(row.reg_total || 0), 0);
  const regKnown = filtered.reduce((sum, row) => sum + Number(row.reg_tyre_known || 0), 0);
  return { regTotal, regKnown, coveragePct: regTotal ? Math.round((1000 * regKnown) / regTotal) / 10 : 0 };
}

export function sliceIceByRimBucket(
  rows: IceRimProvinceRow[], filters: IceMarketFilters = {}, limit = 100,
): MarketSliceRow[] {
  const filtered = rows.filter((row) => passesIceFilters(row, filters));
  const grouped = new Map<string, { label: string; units: number }>();
  let raw = 0;
  for (const row of filtered) {
    const units = Number(row.reg_est || 0);
    raw += units;
    const previous = grouped.get(row.rim_bucket);
    grouped.set(row.rim_bucket, { label: row.rim_bucket, units: (previous?.units || 0) + units });
  }
  return rankedSliceRows(grouped, limit, { raw, mapped: raw });
}

export function sliceIceByTyreSize(
  rows: IceTyreProvinceRow[], filters: IceMarketFilters = {}, limit = 100,
): MarketSliceRow[] {
  const filtered = rows.filter((row) => passesIceFilters(row, filters));
  const grouped = new Map<string, { label: string; units: number }>();
  let raw = 0;
  for (const row of filtered) {
    const units = Number(row.reg_est || 0);
    raw += units;
    const previous = grouped.get(row.tyre_size);
    grouped.set(row.tyre_size, { label: row.tyre_size, units: (previous?.units || 0) + units });
  }
  return rankedSliceRows(grouped, limit, { raw, mapped: raw });
}

// ---------------------------------------------------------------------------
// Percent-change display rule (§14.3 / SKILL.md §4): a percentage change is
// only produced when the comparison base is >= 30 units. This is distinct
// from compareMarketSliceRows' share_change_pp (percentage *points* of market
// share, always computed) -- this is the unit percentage-change figure, and
// it must not exist at all below the threshold, not merely be hidden by a UI.
// ---------------------------------------------------------------------------

export function iceUnitChangePct(previousUnits: number, currentUnits: number): number | null {
  if (previousUnits < 30) return null;
  return Math.round((1000 * (currentUnits - previousUnits)) / previousUnits) / 10;
}

// ---------------------------------------------------------------------------
// Redirect resolver (§14.2 id_changes เปลี่ยนรหัส/รวม; migration_v63's
// ice_model_group_redirects). Pure, deterministic, cycle-safe. This is
// infrastructure for M5's link/bookmark redirection -- it is not wired into
// the slicers above, because the replace-whole-set Ice import model means a
// renamed group's historical rows are already re-labeled under the new id by
// the next full import (migration_v63's own header comment); this resolver
// exists for resolving a STALE external reference (a saved link, an old
// crosswalk row) to the group currently live, not for the aggregation path.
// ---------------------------------------------------------------------------

export type ModelGroupRedirectResolution = { resolved: string; hops: number; cycle: boolean };

export function resolveModelGroupRedirect(
  modelGroupId: string, redirects: IceModelGroupRedirectRow[], maxHops = 10,
): ModelGroupRedirectResolution {
  const byOld = new Map(redirects.map((row) => [row.old_model_group_id, row.new_model_group_id]));
  const seen = new Set<string>([modelGroupId]);
  let current = modelGroupId;
  let hops = 0;
  while (byOld.has(current) && hops < maxHops) {
    const next = byOld.get(current) as string;
    if (seen.has(next)) return { resolved: current, hops, cycle: true };
    seen.add(next);
    current = next;
    hops += 1;
  }
  return { resolved: current, hops, cycle: false };
}

// ---------------------------------------------------------------------------
// Public market assembly -- the pure top-8/others/movers/trend algorithm
// behind `getPublicMarketIce` (lib/ice-public-market.ts), identical to
// lib/public-market.ts's getPublicMarket, factored out here specifically so
// it is unit-testable against synthetic MarketSliceRow[] fixtures with no
// database (see scripts/check-ice-market-engine.ts). Reuses the frozen
// `PublicMarket` type as a type-only import (erased at runtime, so this
// module still has zero runtime dependency on lib/public-market.ts or any
// Supabase client) so the output shape is identical by construction.
// ---------------------------------------------------------------------------

// PR #189 review round 2, fix 1 (option A): PublicMarket's frozen `brands`/
// `movers` entry shape is `{ key, label, registrations, sharePct }` with no
// range field, and that return type is preserved exactly (§15.2: a contract
// function's existing required fields are never renamed/removed). But
// TypeScript's excess-property check only applies to a FRESH object literal
// assigned directly to a typed location -- `named`/`movers` below are built
// via `.map()` into plain variables, so attaching the extra, OPTIONAL
// certainty/registrations_min/registrations_max/note fields (present only
// when `Row` is IcePowertrainSliceRow) onto each entry is a legal "new
// metadata = new optional addition" per §15.2: a caller typed against
// PublicMarket still sees exactly its frozen shape, while a caller that
// knows it asked for the powertrain dimension can read the extra fields
// directly off the same object. This is the chosen fix for "do not silently
// publish a range's midpoint as if it were an exact number" -- never done by
// narrowing precision, only by carrying the fuller shape through when it exists.
function extendedPublicMarketEntry<Row extends MarketSliceRow>(row: Row) {
  const maybeRangeRow = row as Partial<IcePowertrainSliceRow>;
  const extra = maybeRangeRow.certainty !== undefined
    ? {
      certainty: maybeRangeRow.certainty,
      registrations_min: maybeRangeRow.registrations_min,
      registrations_max: maybeRangeRow.registrations_max,
      note: maybeRangeRow.note ?? null,
    }
    : {};
  return {
    key: row.entity_key,
    label: row.entity_label,
    registrations: Number(row.registrations || 0),
    sharePct: Number(row.market_share_pct || 0),
    ...extra,
  };
}

export function assemblePublicMarket<Row extends MarketSliceRow = MarketSliceRow>(args: {
  dimension: PublicMarket["dimension"];
  period: string;
  previousPeriod: string;
  currentRows: Row[];
  currentTotal: number;
  previousRows: Row[];
  brandLimit: number;
  moverLimit?: number;
  trend: { period: string; total: number | null }[];
}): PublicMarket {
  const moverLimit = args.moverLimit ?? 10;
  const named = args.currentRows.slice(0, args.brandLimit).map(extendedPublicMarketEntry);
  const tail = args.currentRows.slice(args.brandLimit);
  const tailUnits = tail.reduce((sum, row) => sum + Number(row.registrations || 0), 0);
  const others = tail.length
    ? { registrations: tailUnits, sharePct: args.currentTotal ? Math.round((10000 * tailUnits) / args.currentTotal) / 100 : 0 }
    : null;

  // compareMarketSliceRows (lib/registration-market.ts) is a pure diff over
  // two already-built MarketSliceRow[] arrays by entity_key -- it carries no
  // legacy mapping-status assumptions, so reusing it exactly here (rather
  // than reimplementing movement math) introduces no legacy semantics.
  const movers = compareMarketSliceRows(args.previousRows, args.currentRows)
    .map((row) => ({ key: row.entity_key, label: row.entity_label, delta: row.units_change, sharePct: row.share_current_pct }))
    .filter((row) => row.delta !== 0)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, moverLimit)
    .sort((a, b) => b.delta - a.delta);

  return {
    dimension: args.dimension,
    period: args.period,
    previousPeriod: args.previousPeriod,
    totalRegistrations: args.currentTotal,
    brands: named,
    others,
    movers,
    trend: args.trend,
  };
}

// ---------------------------------------------------------------------------
// PR #189 review round 2, fix 3: deterministic pagination. The *generic*
// page-walking loop lives here (pure, DB-agnostic, directly unit-testable
// with a fake `fetchPage` -- see scripts/check-ice-market-engine.ts); the
// Supabase-specific half (lib/ice-market-data.ts's pagedSelect) only has to
// build one page's query correctly -- ordered by a table's FULL primary-key
// column list, never by `period` alone, which is not unique and therefore
// not a deterministic sort key on its own (Postgres does not guarantee a
// stable tie-break across repeated reads of an ORDER BY with ties). This
// loop's own job -- walk offset/pageSize until a short page, accumulate,
// never skip or duplicate a row -- is independent of what the ordering is,
// so it is tested here with a plain in-memory array standing in for "a
// correctly, deterministically ordered page source".
// ---------------------------------------------------------------------------

export class PaginationLimitExceededError extends Error {
  constructor(maxRows: number) {
    super(
      `result exceeds the ${maxRows.toLocaleString()}-row safety ceiling -- this must be `
      + "reported loudly, never silently truncated. Raise the ceiling if this is a genuine "
      + "real window, after confirming it is not an ordering/filter bug inflating the count.",
    );
  }
}

export async function fetchAllPages<T>(
  fetchPage: (offset: number, limit: number) => Promise<T[]>,
  pageSize: number,
  maxRows: number,
): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; offset < maxRows; offset += pageSize) {
    const page = await fetchPage(offset, pageSize);
    rows.push(...page);
    if (page.length < pageSize) return rows;
  }
  throw new PaginationLimitExceededError(maxRows);
}

// ---------------------------------------------------------------------------
// PR #189 review round 2, fix 2: "available report periods" must reflect
// every period actually present in the live, already-committed panel data
// (migration_v62's atomic ice_commit_staged_import makes a post-commit read
// safe), not the headline period of each accepted import event
// (ice_package_imports.period) -- a single replace-whole-set release can
// carry many historical periods' worth of rows under one import-log row.
// This is the pure half: deduplicate and sort whatever period strings were
// actually read off a panel table. lib/ice-market-data.ts's iceAvailablePeriods
// is the thin I/O wrapper that pages ice_reg_province's `period` column
// (paginated via fetchAllPages, same determinism/ceiling rules as every
// other fetch) and calls this.
// ---------------------------------------------------------------------------

export function distinctSortedPeriods(periods: Iterable<string>): string[] {
  return [...new Set(periods)].sort();
}
