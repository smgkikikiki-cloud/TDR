/**
 * Load the owner's Ice crosswalk decisions into ice_model_crosswalk_scoped. No AI, no scoring: it copies decisions the owner
 * already made (package ice_crosswalk_r6_offline_recovery_M7.0) and nothing else.
 *
 *   node --experimental-strip-types scripts/ice-scoped-crosswalk-load.ts            # dry run: prints what would be written
 *   node --experimental-strip-types scripts/ice-scoped-crosswalk-load.ts --apply    # writes (needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)
 *
 * Which shadow rows are loaded:
 *   OWNER_APPROVED_LINK, OWNER_APPROVED_AUTO,
 *   PICKUP_RY_SPLIT_SHADOW + REJECTED_CANDIDATE_RECOVERY (only when backed by an owner-overlay line) -> APPROVED  (target must already exist in vehicle_models; otherwise it is reported and skipped)
 *   OWNER_APPROVED_SHADOW_IDENTITY                 -> PENDING   (owner said "create it"; waits for the structural writer)
 *   OWNER_EXCLUDED                                 -> EXCLUDED  (kept in raw totals, left out of coverage)
 * Everything else (low volume, ambiguous, matcher-only suggestions) is NOT loaded: it stays unresolved and goes to the review queue.
 */
import { readFileSync } from "node:fs";
import { Rest } from "../lib/price-refresh/store.ts";

export type ScopedRow = {
  model_group_id: string; reg_type_scope: string; status: "APPROVED" | "EXCLUDED" | "PENDING";
  canonical_model_id: string | null; pending_target_id: string | null;
  master_version: string; decision_ref: string; source_sha256: string; reason: string | null;
};

const PACKAGE = "data/packages/ice_crosswalk_r6_offline_recovery_M7.0";

/** Minimal RFC-4180 reader (quoted fields, doubled quotes, newlines inside quotes). */
export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  const t = text.replace(/^﻿/, "");
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (quoted) {
      if (c === '"' && t[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && t[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const head = rows[0];
  return rows.slice(1).map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

export function buildRows(csv: Record<string, string>[], masterVersion: string): { rows: ScopedRow[]; skipped: Record<string, number> } {
  const rows: ScopedRow[] = [];
  const skipped: Record<string, number> = {};
  for (const r of csv) {
    const d = r.disposition;
    const base = {
      model_group_id: r.source_package_model_group_id || r.model_group_id, reg_type_scope: r.reg_type,
      master_version: masterVersion, decision_ref: r.decision_ref, source_sha256: r.source_package_sha256, reason: r.reason || null,
    };
    if (d === "OWNER_APPROVED_LINK" || d === "OWNER_APPROVED_AUTO" || ((d === "PICKUP_RY_SPLIT_SHADOW" || d === "DETERMINISTIC_REJECTED_CANDIDATE_RECOVERY") && r.decision_ref.startsWith("owner-overlay-line:") && r.target_canonical_id))
      rows.push({ ...base, status: "APPROVED", canonical_model_id: r.target_canonical_id, pending_target_id: null });
    else if (d === "OWNER_APPROVED_SHADOW_IDENTITY")
      rows.push({ ...base, status: "PENDING", canonical_model_id: null, pending_target_id: r.target_canonical_id });
    else if (d === "OWNER_EXCLUDED")
      rows.push({ ...base, status: "EXCLUDED", canonical_model_id: null, pending_target_id: null });
    else skipped[d] = (skipped[d] ?? 0) + 1;
  }
  return { rows, skipped };
}

async function main() {
  const apply = process.argv.includes("--apply");
  const csv = parseCsv(readFileSync(`${PACKAGE}/shadow_crosswalk_rows.csv`, "utf8"));
  const units = new Map(csv.map((r) => [`${r.source_package_model_group_id || r.model_group_id}\u0000${r.reg_type}`, Number(r.reg_count) || 0]));
  const { rows, skipped } = buildRows(csv, "7.0");
  const sum = (list: ScopedRow[]) => list.reduce((a, r) => a + (units.get(`${r.model_group_id}\u0000${r.reg_type_scope}`) ?? 0), 0);
  const by = (s: string) => rows.filter((r) => r.status === s);
  const report: Record<string, unknown> = {
    source_rows: csv.length, to_load: rows.length, approved: by("APPROVED").length, approved_units: sum(by("APPROVED")),
    pending: by("PENDING").length, pending_units: sum(by("PENDING")), excluded: by("EXCLUDED").length, excluded_units: sum(by("EXCLUDED")), not_loaded: skipped,
  };

  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SECRET_KEY;
  if (!url || !key) {
    console.log(JSON.stringify({ mode: "dry-run (no database credentials)", ...report }, null, 2));
    if (apply) { console.error("--apply needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"); process.exit(1); }
    return;
  }
  const rest = new Rest(url, key);
  const known = new Set((await rest.select("vehicle_models", "select=canonical_id&deleted_at=is.null")).map((m) => m.canonical_id as string));
  const missing = by("APPROVED").filter((r) => !known.has(r.canonical_model_id as string));
  const loadable = rows.filter((r) => !missing.includes(r));
  report.approved_target_missing = missing.map((r) => `${r.model_group_id} [${r.reg_type_scope}] -> ${r.canonical_model_id}`);
  report.will_write = loadable.length;
  console.log(JSON.stringify({ mode: apply ? "apply" : "dry-run", ...report }, null, 2));
  if (!apply) return;
  for (let i = 0; i < loadable.length; i += 200)
    await rest.upsert("ice_model_crosswalk_scoped", loadable.slice(i, i + 200), "model_group_id,reg_type_scope");
  console.log(`written ${loadable.length} rows`);
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop() as string)) main().catch((e) => { console.error(e); process.exit(1); });
