/**
 * Market Track R7 -- real-data acceptance checks (pure, no database, no network, no writes).
 * scripts/ice-r7-acceptance.ts loads the live rows read-only and calls runR7Checks();
 * scripts/check-ice-r7-acceptance.ts runs the same function on a small synthetic data set.
 * It judges the SERVING path (scoped crosswalk), the one R8 would switch the website to, not the old group-level crosswalk.
 */
import {
  findPanelRelease,
  resolveIcePowertrainRow,
  resolveWheelTyreAvailability,
  wheelTyreCoverage,
  IcePanelMetadataError,
  type IceRegPowertrainRow,
  type IceRegProvinceRow,
  type IceRegTrendRow,
  type IceTyreCoverageRow,
  type VehicleModelDim,
} from "./ice-market-engine.ts";
import {
  IceScopedResolver,
  scopedCoverage,
  scopedDimensionTotals,
  type OwnerScopedDecision,
  type ScopedResolvedRow,
} from "./ice-scoped-crosswalk.ts";
import { sliceScopedIceMarket } from "./ice-scoped-market-slices.ts";

export type R7Status = "PASS" | "FAIL" | "INFO";
export type R7Check = { id: string; label: string; status: R7Status; detail: Record<string, unknown> | string };
export type R7Input = {
  masterVersion: string;
  period: string;
  panels: unknown;
  trend: readonly IceRegTrendRow[]; // every loaded period
  province: readonly IceRegProvinceRow[]; // latest period
  powertrain: readonly IceRegPowertrainRow[]; // latest period
  tyreCoverage: readonly IceTyreCoverageRow[]; // latest period
  decisions: readonly OwnerScopedDecision[];
  vehicleModels: readonly VehicleModelDim[];
  redirects: readonly { old_model_group_id: string; new_model_group_id: string }[];
  knownGroupIds: readonly string[];
};

const sum = (values: Iterable<number>) => { let t = 0; for (const v of values) t += v; return t; };
const pct = (a: number, b: number) => (b ? Math.round((1000 * a) / b) / 10 : 0);

export function runR7Checks(input: R7Input): R7Check[] {
  const checks: R7Check[] = [];
  const add = (id: string, label: string, status: R7Status, detail: R7Check["detail"]) => checks.push({ id, label, status, detail });
  const { period } = input;

  // The same construction the website would use (lib/ice-market-data.ts getIceScopedMarketSlice).
  const scopedOnly = [...new Set(input.decisions.filter(d => d.reg_type_scope !== "ALL").map(d => d.model_group_id))];
  let resolver: IceScopedResolver;
  try {
    if (!input.decisions.length) throw new Error("scoped crosswalk is empty");
    if (input.decisions.some(d => d.master_version !== input.masterVersion)) throw new Error("a decision has a master_version different from the import");
    resolver = new IceScopedResolver(input.decisions, [], input.vehicleModels.map(m => m.canonical_id), input.masterVersion, scopedOnly);
    add("R7-0", "Scoped decisions load into the resolver (no stale version, duplicate scope, bad status)", "PASS",
      { decisions: input.decisions.length, scoped_only_groups: scopedOnly.length });
  } catch (error) {
    add("R7-0", "Scoped decisions load into the resolver", "FAIL", String((error as Error).message));
    return checks; // nothing else is meaningful
  }

  // R7-1 / R7-2: no unit is dropped by mapping, for every loaded month.
  const periods = [...new Set(input.trend.map(r => r.period))].sort();
  const perPeriod: Record<string, unknown>[] = [];
  let dropped = 0;
  let resolvedLatest: ScopedResolvedRow[] = [];
  for (const p of periods) {
    const rows = input.trend.filter(r => r.period === p);
    const resolved = resolver.resolveRows(rows);
    const raw = sum(rows.map(r => Number(r.reg_count)));
    const cov = scopedCoverage(resolved);
    const byStatus = new Map<string, number>();
    for (const r of resolved) byStatus.set(r.mapping_status, (byStatus.get(r.mapping_status) ?? 0) + Number(r.reg_count));
    const accounted = sum(byStatus.values());
    dropped += Math.abs(raw - accounted) + Math.abs(raw - cov.fixed_denominator);
    perPeriod.push({ period: p, raw, covered: cov.covered_units, excluded: cov.owner_excluded_units,
      covered_pct: Math.round(10 * cov.fixed_denominator_coverage_pct) / 10, other: Object.fromEntries([...byStatus].filter(([s]) => s !== "OWNER_APPROVED" && s !== "OWNER_EXCLUDED")) });
    if (p === period) resolvedLatest = resolved;
  }
  add("R7-1", "No units dropped by mapping (raw = covered + excluded + visibly unresolved), every month", dropped === 0 ? "PASS" : "FAIL",
    { months_checked: periods.length, units_dropped: dropped });
  const worst = [...perPeriod].sort((a, b) => Number(a.covered_pct) - Number(b.covered_pct))[0];
  add("R7-2", "Mapping coverage by month (owner decisions only; informational)", "INFO",
    { latest_12: perPeriod.slice(-12), lowest_month: worst });

  // R7-3: totals reconcile to Ice.
  const latestTrend = input.trend.filter(r => r.period === period);
  const trendTotal = sum(latestTrend.map(r => Number(r.reg_count)));
  const provinceTotal = sum(input.province.map(r => Number(r.reg_count)));
  add("R7-3a", "Ice's own two panels agree for the latest month (reg_province vs reg_trend)", provinceTotal === trendTotal ? "PASS" : "FAIL",
    { period, reg_province_total: provinceTotal, reg_trend_total: trendTotal, delta: provinceTotal - trendTotal });
  const modelSlice = sliceScopedIceMarket({ dimension: "model", facts: latestTrend, ownerDecisions: input.decisions, vehicleModels: input.vehicleModels,
    masterVersion: input.masterVersion, scopedOnlyGroupIds: scopedOnly, limit: 500 });
  const byGroup = new Map<string, number>();
  for (const r of latestTrend) byGroup.set(r.model_group_id, (byGroup.get(r.model_group_id) ?? 0) + Number(r.reg_count));
  const wrong = modelSlice.filter(r => Number(r.registrations) !== (byGroup.get(r.entity_key) ?? -1));
  const sliceTotal = modelSlice.length ? Number(modelSlice[0].market_total) : 0;
  add("R7-3b", "Model slice equals Ice model_group totals; slice market_total equals the month total (up to 500 groups shown)",
    wrong.length === 0 && sliceTotal === trendTotal ? "PASS" : "FAIL",
    { groups_in_data: byGroup.size, groups_in_slice: modelSlice.length, mismatching_groups: wrong.length, slice_market_total: sliceTotal, month_total: trendTotal });

  // R7-4: "ไม่ระบุ" is counted, not hidden.
  const dims: Record<string, unknown> = {};
  let dimsOk = true;
  for (const dimension of ["segment", "body_type"] as const) {
    const totals = scopedDimensionTotals(resolvedLatest, input.vehicleModels, dimension);
    const all = sum(totals.values());
    const unspecified = totals.get("ไม่ระบุ") ?? 0;
    const slice = sliceScopedIceMarket({ dimension, facts: latestTrend, ownerDecisions: input.decisions, vehicleModels: input.vehicleModels,
      masterVersion: input.masterVersion, scopedOnlyGroupIds: scopedOnly, limit: 500 });
    const sliceAll = sum(slice.map(r => Number(r.registrations)));
    const sliceUnspecified = Number(slice.find(r => r.entity_key === "ไม่ระบุ")?.registrations ?? 0);
    if (all !== trendTotal || sliceAll !== trendTotal || sliceUnspecified !== unspecified) dimsOk = false;
    dims[dimension] = { buckets_total: all, slice_total: sliceAll, unspecified_units: unspecified, unspecified_pct: pct(unspecified, trendTotal) };
  }
  add("R7-4", "Segment / body type: every unit lands in a bucket and 'ไม่ระบุ' is counted", dimsOk ? "PASS" : "FAIL", { month_total: trendTotal, ...dims });

  // R7-5: powertrain certainty and ranges survive aggregation. reg_trend must sit inside the group's [min, max] envelope
  // (range rows contribute their min..max, other rows their estimate); the engine's displayed value (range midpoint) is reported separately.
  const lo = new Map<string, number>();
  const hi = new Map<string, number>();
  const est = new Map<string, number>();
  const shown = new Map<string, number>();
  const certainty = new Map<string, number>();
  let badRange = 0;
  for (const row of input.powertrain) {
    const g = row.model_group_id;
    const resolved = resolveIcePowertrainRow(row);
    const e = Number(row.reg_est ?? 0);
    const isRange = row.certainty === "range";
    lo.set(g, (lo.get(g) ?? 0) + (isRange ? Number(row.reg_min ?? 0) : e));
    hi.set(g, (hi.get(g) ?? 0) + (isRange ? Number(row.reg_max ?? 0) : e));
    est.set(g, (est.get(g) ?? 0) + e);
    shown.set(g, (shown.get(g) ?? 0) + resolved.value);
    certainty.set(row.certainty, (certainty.get(row.certainty) ?? 0) + 1);
    if (isRange && !(Number(row.reg_min) <= Number(row.reg_max))) badRange += 1;
  }
  const outside = [...byGroup].filter(([g, t]) => lo.has(g) && (t < (lo.get(g) as number) - 0.5 || t > (hi.get(g) as number) + 0.5));
  const estOff = [...byGroup].filter(([g, t]) => est.has(g) && Math.abs(t - (est.get(g) as number)) > 0.5);
  const shownOff = [...byGroup].filter(([g, t]) => shown.has(g) && Math.abs(t - (shown.get(g) as number)) > 0.5);
  add("R7-5", "Powertrain: reg_trend lies inside each group's min..max envelope; range rows have min <= max", outside.length === 0 && badRange === 0 ? "PASS" : "FAIL",
    { rows: input.powertrain.length, certainty_rows: Object.fromEntries(certainty), groups_outside_envelope: outside.length, bad_ranges: badRange,
      groups_where_ice_estimates_differ_from_trend: estOff.length,
      groups_where_engine_displayed_value_differs_from_trend: shownOff.length,
      sample_displayed_value_differs: shownOff.slice(0, 5).map(([g, t]) => ({ g, trend: t, displayed: shown.get(g), ice_estimate: est.get(g) })) });

  // R7-6: wheel/tyre availability from the persisted period_from, coverage exposed.
  const wheel: Record<string, unknown> = {};
  let wheelOk = true;
  for (const panelId of ["rim_province", "tyre_province"] as const) {
    try {
      const release = findPanelRelease(input.panels, panelId);
      wheel[panelId] = { ...resolveWheelTyreAvailability(release.period_from, period), access: release.access, free_scope: release.free_scope };
    } catch (error) {
      wheelOk = false;
      wheel[panelId] = { error: error instanceof IcePanelMetadataError ? error.message : String(error) };
    }
  }
  add("R7-6", "Wheel/tyre availability comes from the real persisted period_from; tyre coverage is exposed", wheelOk ? "PASS" : "FAIL",
    { ...wheel, tyre_coverage: wheelTyreCoverage([...input.tyreCoverage]) });

  // R7-7: redirects are cycle-safe and point at real groups.
  const next = new Map(input.redirects.map(r => [r.old_model_group_id, r.new_model_group_id]));
  const known = new Set(input.knownGroupIds);
  let cycles = 0;
  for (const start of next.keys()) {
    const seen = new Set<string>([start]);
    for (let cur = next.get(start); cur !== undefined; cur = next.get(cur)) {
      if (seen.has(cur)) { cycles += 1; break; }
      seen.add(cur);
    }
  }
  const dangling = input.redirects.filter(r => !known.has(r.new_model_group_id)).length;
  add("R7-7", "Redirects (Ice id changes) have no cycles; targets exist (dangling targets listed, informational)", cycles === 0 ? "PASS" : "FAIL",
    { redirects: input.redirects.length, cycles, targets_not_in_current_data: dangling });

  // R7-8: serving-contract shape.
  const need = ["entity_key", "entity_label", "registrations", "market_total", "market_share_pct", "market_rank", "window_raw_units", "window_mapped_units", "window_mapping_coverage_pct"];
  const shapeOk = [modelSlice].every(s => s.length > 0 && s.every(r => need.every(k => k in r)));
  add("R7-8", "Slice rows keep the frozen serving-contract shape", shapeOk ? "PASS" : "FAIL", { required_fields: need.length, rows_checked: modelSlice.length });

  return checks;
}
