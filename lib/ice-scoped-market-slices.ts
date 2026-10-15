/**
 * R6 offline / pre-cutover Ice market slices backed by the REVIEWED v2
 * (model_group_id, reg_type_scope) Crosswalk, never by a group-only join.
 *
 * No database access, deployment switch, or legacy registration fallback here.
 * A missing decision is visible as unmapped, never invented or discarded.
 * R8 must independently authorize the website to call this path.
 */
import {
  IceScopedResolver,
  primaryCanonicalForScopedGroup,
  type OwnerScopedDecision,
  type ScopedResolvedRow,
} from "./ice-scoped-crosswalk.ts";
import type {
  IceMarketFilters,
  IceRegTrendRow,
  IceModelSliceRow,
  VehicleModelDim,
} from "./ice-market-engine.ts";
import type { MarketSliceRow } from "./registration-market.ts";

export type ScopedIceDimension = "model" | "segment" | "body_type";
export type ScopedIceSlice = MarketSliceRow[] | IceModelSliceRow[];

type Group = { label: string; units: number };

function filtered(row: IceRegTrendRow, filters: IceMarketFilters): boolean {
  return (!filters.provinces?.length || filters.provinces.includes(row.province))
    && (!filters.registrationTypes?.length || filters.registrationTypes.includes(row.reg_type))
    && (!filters.brands?.length || filters.brands.includes(row.brand))
    && (!filters.modelGroupIds?.length || filters.modelGroupIds.includes(row.model_group_id));
}

function ranked(groups: Map<string, Group>, raw: number, mapped: number, limit: number): MarketSliceRow[] {
  if (!Number.isFinite(limit)) throw new Error("Invalid Ice slice limit");
  const size = Math.min(500, Math.max(1, Math.trunc(limit)));
  const sorted = [...groups].map(([key, val]) => ({ key, ...val }))
    .sort((a, b) => b.units - a.units || a.key.localeCompare(b.key));
  const total = sorted.reduce((sum, item) => sum + item.units, 0);
  const coverage = raw ? Math.round(1000 * mapped / raw) / 10 : 0;
  return sorted.slice(0, size).map((x, index) => ({
    entity_key: x.key,
    entity_label: x.label,
    registrations: x.units,
    market_total: total,
    market_share_pct: total ? Math.round(10000 * x.units / total) / 100 : 0,
    market_rank: index + 1,
    window_raw_units: raw,
    window_mapped_units: mapped,
    window_mapping_coverage_pct: coverage,
  }));
}

function groupRows(rows: readonly ScopedResolvedRow[], dimension: ScopedIceDimension, models: readonly VehicleModelDim[]) {
  const groups = new Map<string, Group>();
  const modelById = new Map(models.map(m => [m.canonical_id, m]));
  let raw = 0;
  let mapped = 0;
  for (const r of rows) {
    const units = Number(r.reg_count);
    if (!Number.isSafeInteger(units) || units < 0) throw new Error("Invalid registration count");
    raw += units;
    let key: string;
    if (dimension === "model") {
      // Ice's model_group_id remains authoritative for model-grain market counts.
      key = r.model_group_id;
      mapped += units; // every Ice model group is a valid RAW market identity
    } else {
      const val = r.canonical_model_id ? modelById.get(r.canonical_model_id)?.[dimension] : null;
      key = val || "ไม่ระบุ";
      if (val) mapped += units;
    }
    const old = groups.get(key);
    groups.set(key, {
      label: dimension === "model" ? [r.brand, r.model_name].filter(Boolean).join(" ") : key,
      units: (old?.units ?? 0) + units,
    });
  }
  return { groups, raw, mapped };
}

/** Pure pre-cutover read model. Never calls the legacy group-level Crosswalk.
 * Caller MUST pass only reviewer-authorized source rows from a pinned Ice
 * master version; passing PROPOSED matches as approvals is a contract violation.
 */
export function sliceScopedIceMarket(args: {
  dimension: ScopedIceDimension;
  facts: readonly IceRegTrendRow[];
  ownerDecisions: readonly OwnerScopedDecision[];
  vehicleModels: readonly VehicleModelDim[];
  masterVersion: string;
  scopedOnlyGroupIds?: readonly string[];
  filters?: IceMarketFilters;
  limit?: number;
}): ScopedIceSlice {
  const { dimension } = args;
  if (dimension !== "model" && dimension !== "segment" && dimension !== "body_type") {
    throw new Error("Unsupported scoped Ice dimension");
  }
  const facts = args.facts.filter(row => filtered(row, args.filters ?? {}));
  // NO ambient v63 AUTO fallback: only rows in the approved v2 decision set
  // may attach a canonical target after R8 cutover.
  const resolver = new IceScopedResolver(
    args.ownerDecisions, [],
    args.vehicleModels.map(model => model.canonical_id),
    args.masterVersion,
    args.scopedOnlyGroupIds ?? [],
  );
  const resolved = resolver.resolveRows(facts);
  const { groups, raw, mapped } = groupRows(resolved, dimension, args.vehicleModels);
  const result = ranked(groups, raw, mapped, args.limit ?? 100);
  if (dimension !== "model") return result;
  // Group-level canonical metadata MUST consider ALL approved class scopes,
  // not just the selected month/province/registration-class filter. Otherwise
  // a pickup group split into RY1 and RY3 appears one-to-one when only RY1
  // was observed in this query window.
  const effectiveTargets = new Map<string, Set<string>>();
  for (const d of args.ownerDecisions) {
    if (d.status === "EXCLUDED") continue;
    const targets = effectiveTargets.get(d.model_group_id) ?? new Set<string>();
    targets.add(d.status === "APPROVED" && d.canonical_model_id
      ? d.canonical_model_id : "__UNRESOLVED_SCOPE__");
    effectiveTargets.set(d.model_group_id, targets);
  }
  return result.map(row => ({
    ...row,
    canonical_model_id: (effectiveTargets.get(row.entity_key)?.size ?? 0) > 1
      ? null
      : primaryCanonicalForScopedGroup(resolved, row.entity_key),
  }));
}
