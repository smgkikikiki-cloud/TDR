/** Offline R6 v2 reader. Apply scoped owner identity to each Ice fact BEFORE totals.
 * No DB/network; not wired to production until a separately gated cutover. */
import type { IceRegTrendRow, IceCrosswalkLink, VehicleModelDim } from "./ice-market-engine.ts";

export type ScopedDecisionStatus = "APPROVED" | "EXCLUDED" | "PENDING";
export type ScopedDisposition = "OWNER_APPROVED" | "OWNER_EXCLUDED" | "OWNER_PENDING"
  | "PENDING_MATERIALIZATION" | "SCOPED_CLASS_UNRESOLVED"
  | "LEGACY_ACTIVE" | "LEGACY_TARGET_MISSING"
  | "AMBIGUOUS_LEGACY_ACTIVE" | "UNMATCHED";
export type OwnerScopedDecision = {
  model_group_id: string; reg_type_scope: string; status: ScopedDecisionStatus;
  canonical_model_id: string | null; decision_ref: string; master_version: string;
};
export type ScopedResolvedRow = IceRegTrendRow & {
  canonical_model_id: string | null;
  mapping_status: ScopedDisposition;
  owner_decision_ref: string | null;
};
export type ScopedCoverage = {
  fixed_denominator: number; owner_excluded_units: number;
  adjusted_denominator: number; covered_units: number;
  fixed_denominator_coverage_pct: number;
};

export function normalizeIceRegType(raw: string): string {
  const value = raw.trim();
  if (value.toUpperCase() === "ALL") return "ALL";
  const match = /^(?:RY|รย\.)\s*(\d+)$/i.exec(value);
  if (!match) throw new Error("Invalid Ice registration type: " + raw);
  return "รย." + Number(match[1]);
}
function decisionKey(group: string, scope: string): string {
  return JSON.stringify([group, scope]);
}

export class IceScopedResolver {
  private readonly ownerByScope = new Map<string, OwnerScopedDecision>();
  private readonly legacyByGroup = new Map<string, Set<string>>();
  private readonly materialized: ReadonlySet<string>;
  private readonly scopedOnly: ReadonlySet<string>;
  constructor(
    owner: readonly OwnerScopedDecision[], legacy: readonly IceCrosswalkLink[],
    materializedCanonicalIds: readonly string[], masterVersion: string,
    scopedOnlyGroupIds: readonly string[] = [],
  ) {
    if (!masterVersion) throw new Error("Ice master_version is required");
    this.materialized = new Set(materializedCanonicalIds);
    this.scopedOnly = new Set(scopedOnlyGroupIds);
    for (const row of owner) {
      const scope = normalizeIceRegType(row.reg_type_scope);
      const key = decisionKey(row.model_group_id, scope);
      if (!row.model_group_id || !row.decision_ref || row.master_version !== masterVersion) {
        throw new Error("Owner decision source/version missing or stale: " + row.model_group_id);
      }
      if (this.ownerByScope.has(key)) throw new Error("Duplicate owner scope: " + key);
      if (!["APPROVED", "EXCLUDED", "PENDING"].includes(row.status)) {
        throw new Error("Unknown scoped owner status: " + row.status);
      }
      if (row.status === "APPROVED" && !row.canonical_model_id) {
        throw new Error("APPROVED owner decision missing target: " + key);
      }
      if (row.status === "EXCLUDED" && row.canonical_model_id !== null) {
        throw new Error("EXCLUDED owner scope cannot have target: " + key);
      }
      this.ownerByScope.set(key, row);
    }
    for (const link of legacy) {
      if (!link.canonical_model_id || (link.status !== "AUTO" && link.status !== "APPROVED")) continue;
      const targets = this.legacyByGroup.get(link.model_group_id) ?? new Set<string>();
      targets.add(link.canonical_model_id);
      this.legacyByGroup.set(link.model_group_id, targets);
    }
  }
  resolve(row: IceRegTrendRow): ScopedResolvedRow {
    const scope = normalizeIceRegType(row.reg_type);
    const units = Number(row.reg_count);
    if (scope === "ALL" || !row.model_group_id || !Number.isFinite(units) || units < 0) {
      throw new Error("Invalid Ice fact grain/count");
    }
    const exact = this.ownerByScope.get(decisionKey(row.model_group_id, scope));
    const decision = exact ?? (this.scopedOnly.has(row.model_group_id)
      ? undefined : this.ownerByScope.get(decisionKey(row.model_group_id, "ALL")));
    const result = (
      canonical_model_id: string | null, mapping_status: ScopedDisposition,
      owner_decision_ref: string | null = null,
    ): ScopedResolvedRow => ({ ...row, canonical_model_id, mapping_status, owner_decision_ref });
    if (decision) {
      if (decision.status === "EXCLUDED") return result(null, "OWNER_EXCLUDED", decision.decision_ref);
      if (decision.status === "PENDING") return result(null, "OWNER_PENDING", decision.decision_ref);
      const target = decision.canonical_model_id!;
      if (!this.materialized.has(target)) return result(null, "PENDING_MATERIALIZATION", decision.decision_ref);
      return result(target, "OWNER_APPROVED", decision.decision_ref);
    }
    if (this.scopedOnly.has(row.model_group_id)) return result(null, "SCOPED_CLASS_UNRESOLVED");
    const targets = this.legacyByGroup.get(row.model_group_id);
    if (!targets?.size) return result(null, "UNMATCHED");
    if (targets.size !== 1) return result(null, "AMBIGUOUS_LEGACY_ACTIVE");
    const target = [...targets][0];
    if (!this.materialized.has(target)) return result(null, "LEGACY_TARGET_MISSING");
    return result(target, "LEGACY_ACTIVE");
  }
  resolveRows(rows: readonly IceRegTrendRow[]): ScopedResolvedRow[] {
    // Period/province repetitions are real facts, not duplicates. Map 1:1.
    return rows.map(row => this.resolve(row));
  }
}
export function scopedCoverage(rows: readonly ScopedResolvedRow[]): ScopedCoverage {
  let fixed = 0, covered = 0, excluded = 0;
  for (const row of rows) {
    const units = Number(row.reg_count);
    fixed += units;
    if (row.canonical_model_id) covered += units;
    if (row.mapping_status === "OWNER_EXCLUDED") excluded += units;
  }
  return {
    fixed_denominator: fixed, owner_excluded_units: excluded,
    adjusted_denominator: fixed - excluded, covered_units: covered,
    fixed_denominator_coverage_pct: fixed ? 100 * covered / fixed : 0,
  };
}
/** Resolve each fact BEFORE segment/body grouping; unknown units stay visible. */
export function scopedDimensionTotals(
  rows: readonly ScopedResolvedRow[], models: readonly VehicleModelDim[],
  dimension: "segment" | "body_type",
): Map<string, number> {
  const byId = new Map(models.map(model => [model.canonical_id, model]));
  const totals = new Map<string, number>();
  for (const row of rows) {
    const value = row.canonical_model_id ? byId.get(row.canonical_model_id)?.[dimension] : null;
    const bucket = value || "ไม่ระบุ";
    totals.set(bucket, (totals.get(bucket) ?? 0) + Number(row.reg_count));
  }
  return totals;
}
/** Group-level canonical metadata only when every nonexcluded class agrees. */
export function primaryCanonicalForScopedGroup(
  rows: readonly ScopedResolvedRow[], modelGroupId: string,
): string | null {
  const relevant = rows.filter(row => row.model_group_id === modelGroupId
    && row.mapping_status !== "OWNER_EXCLUDED");
  if (!relevant.length || relevant.some(row => !row.canonical_model_id)) return null;
  const targets = new Set(relevant.map(row => row.canonical_model_id));
  return targets.size === 1 ? [...targets][0] : null;
}
