/**
 * Phase 1A read-only external-identity audit — live command.
 *
 * Reads, SELECT-only, from three existing tables/views:
 *   - current_vehicle_brands   (Mechanism A, brand scope)
 *   - current_vehicle_models   (Mechanism A, model scope)
 *   - canonical_object_map     (Mechanism B, all scopes it currently uses)
 *
 * It performs no insert/update/delete/upsert and calls no RPC. It never
 * writes to canonical_object_map, crosswalk override files, or release data.
 * See docs/vehicle-platform/EXTERNAL_IDENTITY_CONTRACT.md for what this
 * report does and does not mean.
 *
 * Usage:
 *   node --experimental-strip-types scripts/audit-external-identity.ts
 *
 * Requires the same server-side credentials as every other admin tool in
 * this repository: SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) plus
 * SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_ROLE_KEY). Without a
 * secret key, adminDb() returns null and this script exits without
 * fabricating a report.
 *
 * Prints a human-readable summary to stderr and a deterministic JSON report
 * to stdout, so `... > report.json` captures only the machine-readable form.
 */
import { adminDb } from "../lib/supabase.ts";
import {
  assertionsFromMechanismABrands,
  assertionsFromMechanismAModels,
  assertionsFromMechanismBRows,
  type MechanismABrandRow,
  type MechanismAModelRow,
  type MechanismBRow,
} from "../lib/external-identity/mechanism-adapters.ts";
import { auditAssertions, AUDIT_CLASSIFICATIONS } from "../lib/external-identity/audit.ts";

// Dated reference only — the counts reviewer-supplied evidence recorded on
// 2026-09-15 (docs/vehicle-platform/LIVE_IDENTITY_BASELINE_2026-09-15.md).
// Printed purely so an operator can see drift at a glance; never asserted
// against, never used to gate exit status, and never treated as expected.
const BASELINE_2026_09_15 = {
  date: "2026-09-15",
  mechanismABrandLinks: 62,
  mechanismAModelLinks: 321,
  mechanismATotalLinks: 383,
  mechanismBVerifiedBrandModel: 1,
  mechanismBUnmatchedModel: 326,
};

async function main(): Promise<number> {
  const db = adminDb();
  if (!db) {
    console.error(
      "external-identity audit: no server-side Supabase credentials found " +
        "(need SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL, plus SUPABASE_SECRET_KEY " +
        "or SUPABASE_SERVICE_ROLE_KEY). Nothing was read. Exiting without a report.",
    );
    return 2;
  }

  const [brandsResult, modelsResult, mapResult] = await Promise.all([
    db.from("current_vehicle_brands").select("canonical_id,tdr_brand_id"),
    db.from("current_vehicle_models").select("canonical_id,tdr_model_id"),
    db
      .from("canonical_object_map")
      .select("source_table,source_id,canonical_entity_type,canonical_id,status,match_basis,verified_by,verified_at,notes"),
  ]);

  for (const [label, result] of [
    ["current_vehicle_brands", brandsResult],
    ["current_vehicle_models", modelsResult],
    ["canonical_object_map", mapResult],
  ] as const) {
    if (result.error) {
      console.error(`external-identity audit: read of ${label} failed: ${result.error.message}`);
      console.error("No partial report is printed. Nothing was written or modified.");
      return 1;
    }
  }

  const brandRows = (brandsResult.data ?? []) as MechanismABrandRow[];
  const modelRows = (modelsResult.data ?? []) as MechanismAModelRow[];
  const mapRows = (mapResult.data ?? []) as MechanismBRow[];

  const assertions = [
    ...assertionsFromMechanismABrands(brandRows),
    ...assertionsFromMechanismAModels(modelRows),
    ...assertionsFromMechanismBRows(mapRows),
  ];

  const report = auditAssertions(assertions);

  const generatedAt = new Date().toISOString();
  const mechanismALinks = brandRows.filter((r) => r.tdr_brand_id).length
    + modelRows.filter((r) => r.tdr_model_id).length;
  const mechanismBByStatus: Record<string, number> = {};
  for (const row of mapRows) mechanismBByStatus[row.status] = (mechanismBByStatus[row.status] ?? 0) + 1;

  console.error(`external-identity audit — live, read-only, generated ${generatedAt}`);
  console.error(`  Mechanism A (release crosswalk): ${mechanismALinks} resolved links `
    + `(${brandRows.filter((r) => r.tdr_brand_id).length} brand, ${modelRows.filter((r) => r.tdr_model_id).length} model)`);
  console.error(`  Mechanism B (canonical_object_map): ${mapRows.length} rows, by status: `
    + JSON.stringify(mechanismBByStatus));
  console.error(`  Audit findings: ${report.summary.totalFindings} comparability groups`);
  for (const classification of AUDIT_CLASSIFICATIONS) {
    console.error(`    ${classification}: ${report.summary.byClassification[classification]}`);
  }
  console.error(
    `  External IDs with assertions at more than one canonical entity type: `
      + `${report.summary.externalIdentitiesWithMultipleCanonicalEntityTypes}`,
  );
  console.error("");
  console.error(
    `  For reference, dated baseline ${BASELINE_2026_09_15.date} recorded ` +
      `${BASELINE_2026_09_15.mechanismATotalLinks} Mechanism A links and ` +
      `${BASELINE_2026_09_15.mechanismBVerifiedBrandModel} verified Mechanism B Brand/Model link ` +
      `(docs/vehicle-platform/LIVE_IDENTITY_BASELINE_2026-09-15.md). This is historical context ` +
      `only — current counts above are authoritative, and drift from that date is expected and fine.`,
  );
  console.error("");
  console.error("Machine-readable report follows on stdout.");

  console.log(
    JSON.stringify(
      {
        generatedAt,
        source: "live_supabase",
        readOnly: true,
        tablesRead: ["current_vehicle_brands", "current_vehicle_models", "canonical_object_map"],
        report,
      },
      null,
      2,
    ),
  );

  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error("external-identity audit: unexpected error, no report produced:", error);
    process.exit(1);
  });
