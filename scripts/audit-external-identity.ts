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
 * Read-only boundary, precisely: this script's SELECT-only behavior is
 * enforced by its own code — there is no other call in this file, and
 * nothing it imports issues a write. It is NOT enforced by the database
 * credential it uses: `adminDb()` returns the same server-side
 * Supabase admin/service-role client every other admin tool in this
 * repository uses, which is fully write-capable at the credential level.
 * Phase 1A introduces no dedicated least-privilege read-only database role
 * or key. Creating one would be a separate infrastructure/security decision
 * and is not authorized by this script's existence — see
 * EXTERNAL_IDENTITY_CONTRACT.md's "Read-only boundary" section.
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

// Dated reference only — see
// docs/vehicle-platform/PHASE_1A_LIVE_VALIDATION_2026-09-15.md, an
// architecture-review-supplied live result produced independently of this
// checked-in CLI (this CLI has never been run against production — no
// session implementing or hardening Phase 1A had live credentials). Printed
// purely so an operator can see drift at a glance; never asserted against,
// never used to gate exit status, and never treated as expected.
const REVIEWER_VALIDATION_2026_09_15 = {
  date: "2026-09-15",
  mechanismAAssertions: 383,
  mechanismBRows: 335,
  totalComparabilityGroups: 397,
  exactAgreement: 1,
  disagreement: 0,
  derivedOnly: 62,
  verifiedOnly: 8,
  mechanismBUnmatched: 326,
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

  const mechanismAAssertions = [
    ...assertionsFromMechanismABrands(brandRows),
    ...assertionsFromMechanismAModels(modelRows),
  ];
  const { assertions: mechanismBAssertions, invalidRows } = assertionsFromMechanismBRows(mapRows);
  const assertions = [...mechanismAAssertions, ...mechanismBAssertions];

  const report = auditAssertions(assertions);

  const generatedAt = new Date().toISOString();
  const mechanismBByStatus: Record<string, number> = {};
  for (const row of mapRows) mechanismBByStatus[row.status] = (mechanismBByStatus[row.status] ?? 0) + 1;

  console.error(`external-identity audit — live, read-only, generated ${generatedAt}`);
  console.error(`  Mechanism A (release crosswalk): ${mechanismAAssertions.length} resolved links `
    + `(${brandRows.filter((r) => r.tdr_brand_id).length} brand, ${modelRows.filter((r) => r.tdr_model_id).length} model)`);
  console.error(`  Mechanism B (canonical_object_map): ${mapRows.length} rows, by status: `
    + JSON.stringify(mechanismBByStatus));
  if (invalidRows.length > 0) {
    console.error(
      `  WARNING: ${invalidRows.length} Mechanism B row(s) could not become an assertion at all `
        + `(fail-closed, not silently dropped or downgraded to unmatched) — see "invalidMechanismBRows" `
        + `in the JSON report below. This should never happen live: canonical_object_map's own check `
        + `constraint forbids status='verified' with a null canonical_id.`,
    );
  }
  console.error(`  Audit findings: ${report.summary.totalFindings} comparability groups`);
  for (const classification of AUDIT_CLASSIFICATIONS) {
    console.error(`    ${classification}: ${report.summary.byClassification[classification]}`);
  }
  if (report.anomalies.length > 0) {
    console.error(
      `  WARNING: ${report.anomalies.length} anomaly group(s) excluded from findings — more than one `
        + `assertion from the same mechanism under one comparability key. See "anomalies" in the JSON `
        + `report below. No row was arbitrarily selected as that mechanism's answer.`,
    );
  }
  console.error(
    `  External IDs with assertions at more than one canonical entity type: `
      + `${report.summary.externalIdentitiesWithMultipleCanonicalEntityTypes}`,
  );
  console.error("");
  console.error(
    `  For reference, an architecture-review-supplied live validation dated ` +
      `${REVIEWER_VALIDATION_2026_09_15.date} recorded ${REVIEWER_VALIDATION_2026_09_15.mechanismAAssertions} ` +
      `Mechanism A assertions and ${REVIEWER_VALIDATION_2026_09_15.mechanismBRows} Mechanism B rows across ` +
      `${REVIEWER_VALIDATION_2026_09_15.totalComparabilityGroups} comparability groups ` +
      `(docs/vehicle-platform/PHASE_1A_LIVE_VALIDATION_2026-09-15.md). That result was produced independently ` +
      `by the architecture reviewer using equivalent SELECT-only logic — this checked-in CLI was not the tool ` +
      `that ran it. This is historical context only; current counts above are authoritative, and drift from ` +
      `that date is expected and fine.`,
  );
  console.error("");
  console.error("Machine-readable report follows on stdout.");

  console.log(
    JSON.stringify(
      {
        generatedAt,
        source: "live_supabase",
        readOnly: true,
        readOnlyEnforcement: "code-only (SELECT-only calls in this script); the Supabase credential itself is the standard write-capable server-side admin/service-role client, not a database-enforced read-only role",
        tablesRead: ["current_vehicle_brands", "current_vehicle_models", "canonical_object_map"],
        invalidMechanismBRows: invalidRows,
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
