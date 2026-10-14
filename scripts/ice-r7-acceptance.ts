/**
 * Market Track R7 -- real-data acceptance. READ-ONLY: only SELECTs, never writes.
 *   SUPABASE_URL=... SUPABASE_SECRET_KEY=... node --experimental-strip-types scripts/ice-r7-acceptance.ts [period]
 * Prints a JSON report and exits 1 when any check FAILs. Judges the scoped crosswalk path (what R8 would serve).
 */
import { createClient } from "@supabase/supabase-js";
import { runR7Checks } from "../lib/ice-r7-acceptance.ts";

const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!url || !key) { console.error("SUPABASE_URL and SUPABASE_SECRET_KEY (service role) are required."); process.exit(1); }
const db = createClient(url, key, { auth: { persistSession: false } });

/** Pages through one table in a stable order (the table's natural key), optionally for one period. */
async function all<T>(table: string, columns: string, orderBy: string[], period?: string): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; ; offset += 1000) {
    let q = db.from(table).select(columns);
    if (period) q = q.eq("period", period);
    for (const column of orderBy) q = q.order(column, { ascending: true });
    const { data, error } = await q.range(offset, offset + 999);
    if (error) throw new Error(`${table}: ${error.message}`);
    rows.push(...((data ?? []) as T[]));
    if (!data || data.length < 1000) return rows;
  }
}
async function plain<T>(table: string, columns: string): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; ; offset += 1000) {
    const { data, error } = await db.from(table).select(columns).range(offset, offset + 999);
    if (error) throw new Error(`${table}: ${error.message}`);
    rows.push(...((data ?? []) as T[]));
    if (!data || data.length < 1000) return rows;
  }
}

async function main() {
  const { data: imports, error } = await db.from("ice_package_imports").select("period,master_version,panels").order("imported_at", { ascending: false }).limit(1);
  if (error) throw new Error(error.message);
  if (!imports?.length) { console.log(JSON.stringify({ status: "no_import" })); process.exit(1); }
  const period = process.argv[2] || String(imports[0].period);
  const [trend, province, powertrain, tyreCoverage, decisions, vehicleModels, redirects, known] = await Promise.all([
    all<any>("ice_reg_trend", "period,province,reg_type,brand,model_group_id,model_name,reg_count", ["period", "province", "reg_type", "brand", "model_group_id"]),
    all<any>("ice_reg_province", "period,province,reg_type,brand,fuel_group,reg_count", ["province", "reg_type", "brand", "fuel_group"], period),
    all<any>("ice_reg_powertrain", "period,province,reg_type,brand,model_group_id,model_name,fuel_group,reg_est,reg_min,reg_max,certainty", ["province", "reg_type", "brand", "model_group_id", "fuel_group"], period),
    all<any>("ice_tyre_coverage", "period,province,reg_type,brand,reg_total,reg_tyre_known", ["province", "reg_type", "brand"], period),
    plain<any>("ice_model_crosswalk_scoped", "model_group_id,reg_type_scope,status,canonical_model_id,decision_ref,master_version"),
    plain<any>("vehicle_models", "canonical_id,segment,body_type"),
    plain<any>("ice_model_group_redirects", "old_model_group_id,new_model_group_id"),
    plain<any>("ice_dims_model_group", "model_group_id"),
  ]);
  const checks = runR7Checks({
    masterVersion: String(imports[0].master_version), period, panels: imports[0].panels,
    trend, province, powertrain, tyreCoverage, decisions, vehicleModels, redirects,
    knownGroupIds: known.map((r: any) => r.model_group_id),
  });
  const failed = checks.filter(c => c.status === "FAIL");
  console.log(JSON.stringify({ status: failed.length ? "FAIL" : "PASS", period, master_version: imports[0].master_version,
    rows_loaded: { trend: trend.length, province: province.length, powertrain: powertrain.length }, checks }, null, 2));
  process.exit(failed.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(1); });
