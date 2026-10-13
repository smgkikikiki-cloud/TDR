/** Offline M4 reader adapter for the reviewed R6 scoped crosswalk. */
import type { IceRegTrendRow, IceCrosswalkLink, VehicleModelDim } from "./ice-market-engine.ts";
import { IceScopedResolver, normalizeIceRegType, type OwnerScopedDecision, type ScopedDisposition } from "./ice-scoped-crosswalk.ts";

export type ScopedReaderFact = IceRegTrendRow & {
  canonical_model_id: string | null;
  mapping_status: ScopedDisposition;
  owner_decision_ref: string | null;
};

export type ScopedReaderSummary = {
  raw_registrations: number;
  resolved_fact_count: number;
  canonical_model_totals: Record<string, number>;
  segment_totals: Record<string, number>;
  body_type_totals: Record<string, number>;
  mapping_status_totals: Record<string, number>;
  period_province_reg_type_totals: Array<{
    period: string; province: string; reg_type: string; registrations: number;
  }>;
};

/** Map every delivered Ice row before any derived grouping; never deduplicate. */
export function readScopedRegistrationRows(
  rows: readonly IceRegTrendRow[],
  owner: readonly OwnerScopedDecision[],
  legacy: readonly IceCrosswalkLink[],
  materializedCanonicalIds: readonly string[],
  masterVersion: string,
  scopedOnlyGroupIds: readonly string[] = [],
): ScopedReaderFact[] {
  const resolver = new IceScopedResolver(
    owner, legacy, materializedCanonicalIds, masterVersion, scopedOnlyGroupIds,
  );
  return resolver.resolveRows(rows).map(row => ({
    ...row, reg_type: normalizeIceRegType(row.reg_type),
  }));
}

/** Totals conserve every raw unit, with unresolved mappings in explicit buckets. */
export function scopedReaderTotals(
  rows: readonly ScopedReaderFact[], models: readonly VehicleModelDim[],
): ScopedReaderSummary {
  const dimensions = new Map(models.map(model => [model.canonical_id, model]));
  const modelTotals = new Map<string, number>();
  const segmentTotals = new Map<string, number>();
  const bodyTotals = new Map<string, number>();
  const statusTotals = new Map<string, number>();
  const scopeTotals = new Map<string, { period: string; province: string; reg_type: string; registrations: number }>();
  const raw = rows.reduce((sum, row) => sum + row.reg_count, 0);
  for (const row of rows) {
    const units = row.reg_count;
    const modelKey = row.canonical_model_id ?? "UNMAPPED";
    modelTotals.set(modelKey, (modelTotals.get(modelKey) ?? 0) + units);
    statusTotals.set(row.mapping_status, (statusTotals.get(row.mapping_status) ?? 0) + units);
    const model = row.canonical_model_id ? dimensions.get(row.canonical_model_id) : undefined;
    const segment = model?.segment || "ไม่ระบุ";
    const body = model?.body_type || "ไม่ระบุ";
    segmentTotals.set(segment, (segmentTotals.get(segment) ?? 0) + units);
    bodyTotals.set(body, (bodyTotals.get(body) ?? 0) + units);
    const scopeKey = JSON.stringify([row.period, row.province, row.reg_type]);
    const scope = scopeTotals.get(scopeKey) ?? {
      period: row.period, province: row.province, reg_type: row.reg_type, registrations: 0,
    };
    scope.registrations += units;
    scopeTotals.set(scopeKey, scope);
  }
  const reconcile = (name: string, totals: Map<string, number>) => {
    const sum = [...totals.values()].reduce((a, b) => a + b, 0);
    if (sum !== raw) throw new Error(`${name} does not reconcile: ${sum} != ${raw}`);
  };
  for (const [name, totals] of [
    ["model", modelTotals], ["segment", segmentTotals], ["body", bodyTotals], ["status", statusTotals],
  ] as const) reconcile(name, totals);
  if ([...scopeTotals.values()].reduce((sum, row) => sum + row.registrations, 0) !== raw) {
    throw new Error("period/province/reg_type does not reconcile to raw Ice registrations");
  }
  const sortedRecord = (map: Map<string, number>) => Object.fromEntries([...map.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
  return {
    raw_registrations: raw,
    resolved_fact_count: rows.length,
    canonical_model_totals: sortedRecord(modelTotals),
    segment_totals: sortedRecord(segmentTotals),
    body_type_totals: sortedRecord(bodyTotals),
    mapping_status_totals: sortedRecord(statusTotals),
    period_province_reg_type_totals: [...scopeTotals.values()].sort((a, b) =>
      (a.period < b.period ? -1 : a.period > b.period ? 1 : 0)
      || (a.province < b.province ? -1 : a.province > b.province ? 1 : 0)
      || (a.reg_type < b.reg_type ? -1 : a.reg_type > b.reg_type ? 1 : 0)),
  };
}
