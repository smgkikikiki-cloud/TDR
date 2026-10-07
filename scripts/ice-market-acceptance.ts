/**
 * Market Track M4 -- real-package acceptance harness (item 13 of the M4 brief).
 *
 * READ-ONLY. Never writes to any table, never approves/seeds a crosswalk
 * mapping, never alters Ice data. Run this once a real Ice Full Package and a
 * real crosswalk review exist in production, to confirm the M4 engine
 * reconciles against the live Ice data before M5 switches any page to it.
 *
 *   SUPABASE_URL=... SUPABASE_SECRET_KEY=... \
 *     node --experimental-strip-types scripts/ice-market-acceptance.ts [period]
 *
 * `period` is an optional Buddhist "YYYY-MM" string; defaults to the latest
 * accepted import's period (ice_package_imports, ordered by imported_at).
 *
 * This script talks to Supabase directly (createClient), the same way
 * scripts/publish-official-media.ts does, rather than importing
 * lib/ice-market-data.ts -- that module uses this repo's "@/lib/..." path
 * alias, which only the Next.js build resolves, not a plain `node` run (see
 * lib/ice-market-engine.ts's own doc comment on this). The aggregation logic
 * itself IS imported, via a relative path, from lib/ice-market-engine.ts --
 * the pure engine functions this reconciliation calls are the exact same code
 * the rest of M4 is built on, not a reimplementation.
 */
import { createClient } from "@supabase/supabase-js";
import {
  findPanelRelease,
  resolveIcePowertrainRow,
  resolveWheelTyreAvailability,
  sliceIceByBodyType,
  sliceIceByBrand,
  sliceIceByModel,
  sliceIceByPowertrain,
  sliceIceBySegment,
  wheelTyreCoverage,
  IcePanelMetadataError,
  type IceCrosswalkLink,
  type IceRegPowertrainRow,
  type IceRegProvinceRow,
  type IceRegTrendRow,
  type IceTyreCoverageRow,
  type VehicleModelDim,
} from "../lib/ice-market-engine.ts";

const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!url || !key) {
  console.error("SUPABASE_URL and SUPABASE_SECRET_KEY (service role) are required.");
  process.exit(1);
}
const db = createClient(url, key, { auth: { persistSession: false } });

async function fetchAll<T>(table: string, columns: string, period: string): Promise<T[]> {
  const rows: T[] = [];
  const pageSize = 1000;
  for (let offset = 0; ; offset += pageSize) {
    const { data, error } = await db.from(table).select(columns).eq("period", period).range(offset, offset + pageSize - 1);
    if (error) throw new Error(`${table} query failed: ${error.message}`);
    const page = (data ?? []) as T[];
    rows.push(...page);
    if (page.length < pageSize) return rows;
  }
}

async function main() {
  const requestedPeriod = process.argv[2] || null;

  const { data: imports, error: importError } = await db
    .from("ice_package_imports")
    .select("period,master_version,panels,imported_at")
    .order("imported_at", { ascending: false })
    .limit(1);
  if (importError) throw new Error(`ice_package_imports query failed: ${importError.message}`);
  if (!imports?.length) {
    console.log(JSON.stringify({ status: "no_import", message: "ice_package_imports is empty -- no real package has been imported yet." }, null, 2));
    return;
  }
  const period = requestedPeriod || String(imports[0].period);
  const masterVersion = String(imports[0].master_version);
  const panels = imports[0].panels;

  const [province, trend, powertrain, crosswalkRows, modelRows, coverageRows] = await Promise.all([
    fetchAll<IceRegProvinceRow>("ice_reg_province", "period,province,reg_type,brand,fuel_group,reg_count", period),
    fetchAll<IceRegTrendRow>("ice_reg_trend", "period,province,reg_type,brand,model_group_id,model_name,reg_count", period),
    fetchAll<IceRegPowertrainRow>(
      "ice_reg_powertrain",
      "period,province,reg_type,brand,model_group_id,model_name,fuel_group,reg_est,reg_min,reg_max,certainty", period),
    db.from("ice_model_crosswalk").select("model_group_id,canonical_model_id,status"),
    db.from("vehicle_models").select("canonical_id,segment,body_type"),
    fetchAll<IceTyreCoverageRow>("ice_tyre_coverage", "period,province,reg_type,brand,reg_total,reg_tyre_known", period),
  ]);
  const crosswalk = (crosswalkRows.data ?? []) as IceCrosswalkLink[];
  const models = (modelRows.data ?? []) as VehicleModelDim[];

  const iceProvinceTotal = province.reduce((sum, row) => sum + Number(row.reg_count || 0), 0);
  const iceTrendTotal = trend.reduce((sum, row) => sum + Number(row.reg_count || 0), 0);

  const brandSlice = sliceIceByBrand(province, {}, 500);
  const modelSlice = sliceIceByModel(trend, crosswalk, {}, 500);
  const engineBrandTotal = brandSlice.reduce((sum, row) => sum + Number(row.registrations), 0);
  const engineModelTotal = modelSlice.reduce((sum, row) => sum + Number(row.registrations), 0);

  const segmentSlice = sliceIceBySegment(trend, crosswalk, models, {}, 500);
  const bodySlice = sliceIceByBodyType(trend, crosswalk, models, {}, 500);
  const segmentCoverage = segmentSlice.length ? segmentSlice[0].window_mapping_coverage_pct : null;
  const bodyCoverage = bodySlice.length ? bodySlice[0].window_mapping_coverage_pct : null;
  const unmatchedModelGroupIds = [...new Set(trend.map((row) => row.model_group_id))]
    .filter((id) => !crosswalk.some((link) => link.model_group_id === id
      && link.canonical_model_id && (link.status === "AUTO" || link.status === "APPROVED")));

  const powertrainResolved = powertrain.map(resolveIcePowertrainRow);
  const powertrainTotal = powertrainResolved.reduce((sum, row) => sum + row.value, 0);
  const powertrainSlice = sliceIceByPowertrain(powertrain, {}, 500);
  // SKILL.md §2 step 4: reg_powertrain sums ≈ reg_trend per model_group_id, ±0.5.
  const trendByModel = new Map<string, number>();
  for (const row of trend) trendByModel.set(row.model_group_id, (trendByModel.get(row.model_group_id) || 0) + Number(row.reg_count || 0));
  const powertrainByModel = new Map<string, number>();
  for (const row of powertrain) {
    const { value } = resolveIcePowertrainRow(row);
    powertrainByModel.set(row.model_group_id, (powertrainByModel.get(row.model_group_id) || 0) + value);
  }
  const powertrainMismatches: { model_group_id: string; trend: number; powertrain: number; delta: number }[] = [];
  for (const [modelGroupId, trendTotal] of trendByModel) {
    const powertrainTotalForModel = powertrainByModel.get(modelGroupId);
    if (powertrainTotalForModel == null) continue; // no powertrain rows for this model -- not a mismatch, just absent
    const delta = Math.abs(trendTotal - powertrainTotalForModel);
    if (delta > 0.5) powertrainMismatches.push({ model_group_id: modelGroupId, trend: trendTotal, powertrain: powertrainTotalForModel, delta });
  }

  const coverage = wheelTyreCoverage(coverageRows);
  // period_from/access/free_scope are persisted per panel in ice_package_imports.panels
  // (R1/M2.1) -- read via findPanelRelease, never hard-coded. rim_province and
  // tyre_province persist their own period_from independently, so each is read
  // and reported on its own panel entry, not shared. A panel whose metadata is
  // missing/malformed is reported explicitly (error), never guessed around.
  function wheelTyrePanelReport(panelId: "rim_province" | "tyre_province") {
    try {
      const release = findPanelRelease(panels, panelId);
      return { ...resolveWheelTyreAvailability(release.period_from, period), access: release.access, free_scope: release.free_scope, error: null };
    } catch (error) {
      if (error instanceof IcePanelMetadataError) return { available: null, periodFrom: null, access: null, free_scope: null, error: error.message };
      throw error;
    }
  }
  const wheelTyreAvailability = { rim_province: wheelTyrePanelReport("rim_province"), tyre_province: wheelTyrePanelReport("tyre_province") };

  const report = {
    period,
    master_version: masterVersion,
    totals: {
      ice_reg_province_total: iceProvinceTotal,
      engine_brand_total: engineBrandTotal,
      brand_delta: iceProvinceTotal - engineBrandTotal,
      ice_reg_trend_total: iceTrendTotal,
      engine_model_total: engineModelTotal,
      model_delta: iceTrendTotal - engineModelTotal,
      reg_province_vs_reg_trend_delta: iceProvinceTotal - iceTrendTotal,
    },
    segment: { mapping_coverage_pct: segmentCoverage, unmapped_bucket: segmentSlice.find((r) => r.entity_key === "ไม่ระบุ") ?? null },
    body_type: { mapping_coverage_pct: bodyCoverage },
    unmatched_model_group_ids: unmatchedModelGroupIds,
    powertrain: {
      total: powertrainTotal,
      engine_total: powertrainSlice.reduce((sum, row) => sum + Number(row.registrations), 0),
      reconciliation_status: powertrainMismatches.length ? "MISMATCH" : "OK",
      mismatches: powertrainMismatches,
    },
    wheel_tyre: { coverage, availability: wheelTyreAvailability },
    contract_shape_check: {
      brand_rows_have_market_slice_row_shape: brandSlice.every((row) =>
        "entity_key" in row && "entity_label" in row && "registrations" in row && "market_total" in row
        && "market_share_pct" in row && "market_rank" in row && "window_raw_units" in row
        && "window_mapped_units" in row && "window_mapping_coverage_pct" in row),
    },
  };

  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
