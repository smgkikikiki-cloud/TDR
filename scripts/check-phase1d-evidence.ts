import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const readJson = (path: string) => JSON.parse(readFileSync(resolve(root, path), "utf8"));
const hash = (path: string) => createHash("sha256").update(readFileSync(resolve(root, path))).digest("hex");
const reportPath = "docs/vehicle-db/phase1d/acceptance_report.json";
const coveragePath = "docs/vehicle-db/phase1d/full_catalog_coverage_manifest.json";
const report = readJson(reportPath);
const coverage = readJson(coveragePath);
const snapshotPath = "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/vehicle_master_identity_snapshot_2026-10-13.json";
const snapshot = readJson(snapshotPath);
const frozenPath = "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/owner_decision_ledger_244.csv";

assert.equal(report.schema, "tdr.vehicle-db.phase1d.acceptance.v1");
assert.equal(report.base_sha, "01ff6af90d488e5b3b990a74dc89ad5a2af7bbb2");
assert.equal(report.acceptance_result, "BLOCKED");
assert.equal(report.production_ready, false);
assert.equal(coverage.status, "FULL_CATALOG_ACCEPTANCE_BLOCKED");
assert.equal(coverage.acceptance_claimed, false);
assert.equal(coverage.snapshot.sha256, hash(snapshotPath));
assert.equal(coverage.snapshot.sha256, "cf991264ada90efb0ff69a754cdee11fb0d13cc98fbe9fc60879de4eb7a2eb62");
assert.equal(snapshot.read_only, true);
assert.equal(snapshot.project_ref, coverage.snapshot.project_ref);
assert.equal(snapshot.captured_at_utc, coverage.snapshot.captured_at_utc);
assert.deepEqual(Object.keys(snapshot.relations).sort(), ["vehicle_brands", "vehicle_generations", "vehicle_models"]);
assert.deepEqual(Object.fromEntries(Object.entries(snapshot.relations).map(([name, rel]: [string, any]) => [name, rel.observed_rows])), {
  vehicle_brands: 62, vehicle_models: 323, vehicle_generations: 326,
});
assert.equal(coverage.required_but_missing.includes("vehicle_variants"), true);
assert.equal(coverage.required_but_missing.includes("vehicle_trims"), true);
assert.equal(coverage.catalog_acceptance.baseline_on_full_catalog, "NOT_RUN_NO_COMPLETE_AUTHORIZED_INPUT");
assert.equal(coverage.catalog_acceptance.basic_identity_public_exclusion, "PROVEN_ONLY_IN_PHASE1C_SINGLE_TOYOTA_FIXTURE");
assert.equal(hash(frozenPath), report.frozen_inputs.owner_ledger_sha256);
assert.equal(hash(frozenPath), "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8");
assert.equal(readFileSync(resolve(root, frozenPath), "utf8").trimEnd().split(/\r?\n/).length - 1, 244);
assert.deepEqual(report.frozen_inputs, {
  owner_decisions: 244,
  owner_ledger_sha256: "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8",
  scopes: 1407,
  registration_units: 4141987,
  effective_units: 4123704,
  excluded_units: 18283,
  basic_candidates: 8,
  candidate_units: 47109,
  raptor_hold_units: 12839,
  simulated_coverage_percent: 98.819047,
  new_approved_or_servable_units: 0,
});
for (const gate of ["FULL_CATALOG_ACCEPTANCE_BLOCKED", "ADMIN_AUTH_ACCEPTANCE_BLOCKED", "MIGRATION_GATE_BLOCKED", "ENFORCER_ADMISSION_BLOCKED"]) {
  assert.equal(report.gates[gate].status, "BLOCKED", `${gate} must not be silently reported as accepted`);
}
assert.equal(report.gates.FULL_CATALOG_ACCEPTANCE_BLOCKED.full_catalog_parity_claimed, false);
assert.equal(report.gates.ADMIN_AUTH_ACCEPTANCE_BLOCKED.admin_helper_tests_are_production_authorization, false);
assert.equal(report.gates.MIGRATION_GATE_BLOCKED.migration_number_allocated, false);
assert.equal(report.evidence.mock_only_results_substituted, false);
assert.equal(report.actions_prohibited_and_not_performed.production_or_staging_writes, 0);
assert.equal(report.actions_prohibited_and_not_performed.migrations_executed, 0);
assert.equal(report.actions_prohibited_and_not_performed.merge_or_deployment, false);
for (const migration of report.repository_migration_evidence.hashes_v57_v66) {
  assert.equal(hash(migration.file), migration.sha256, `repository migration hash mismatch: ${migration.file}`);
}

console.log("PASS Phase 1D evidence provenance, partial catalog coverage, frozen inputs, and blocked-gate invariants");
