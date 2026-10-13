/** Reproducible read-only-source preflight. Any writes below are to the test double. */
import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { StructuralIdentityWriter, planStructuralChanges, flattenIdentityAliases, structuralHash,
  type Snapshot, type Batch, type Intent } from "../lib/vehicle-engine/structural-writer.ts";
import { MemoryIdentityStore } from "./test-support/structural-identity-store.ts";

const directory = "docs/vehicle-db/structural-writer";
const input = JSON.parse(fs.readFileSync(`${directory}/nine_identity_inputs.json`, "utf8"));
const sha = (data: Buffer) => createHash("sha256").update(data).digest("hex");
for (const [path, hash] of Object.entries(input.source_files_sha256)) assert.equal(sha(fs.readFileSync(path)), hash, "Frozen source changed: " + path);
const catalog = JSON.parse(fs.readFileSync(input.catalog_path, "utf8"));
const snapshot: Snapshot = {
  vehicle_brands: catalog.relations.vehicle_brands.rows.map((r: any) => ({ ...r, aliases: flattenIdentityAliases(r.aliases) })),
  vehicle_models: catalog.relations.vehicle_models.rows.map((r: any) => ({ ...r, aliases: flattenIdentityAliases(r.aliases) })),
  ice_model_crosswalk_scoped: [], ice_scopes: input.candidates.flatMap((c: any) => c.source_scopes), tdr_classifications: [],
};
const initial = structuralHash(snapshot);
function batch(id: string, intents: Intent[], raw: any = {}): Batch { return { batch_id: id, reason: "Issue 236 frozen nine-identity offline preflight",
  source_ref: `PR235:${input.source_commit}`, observed_at: "2026-10-13T00:00:00Z", intents, raw_evidence: raw }; }
const candidates = input.candidates.map((c: any) => {
  const plan = planStructuralChanges(snapshot, batch("preflight:" + c.canonical_id, [c.create_intent], c.raw_ice_evidence));
  return { canonical_id: c.canonical_id, model_name: c.name, registrations: c.registrations,
    class_scopes: c.source_scopes, disposition: plan.holds.length ? "REVIEW_HOLD" : "VALID_BASIC_IDENTITY_PROPOSAL",
    holds: plan.holds, canonical_segment: "UNKNOWN", canonical_body_type: "UNKNOWN", canonical_generation: "UNKNOWN",
    lifecycle_status: "UNKNOWN", raw_ice_classification_evidence: c.raw_ice_evidence, requires_admin_create_authorization: true,
    requires_separate_r6_link_authorization: true, safe_candidate_was_not_treated_as_create_approval: true };
});
const validIds = new Set(candidates.filter((c: any) => c.disposition === "VALID_BASIC_IDENTITY_PROPOSAL").map((c: any) => c.canonical_id));
const holds = candidates.filter((c: any) => c.disposition === "REVIEW_HOLD");
const accepted = input.candidates.filter((c: any) => validIds.has(c.canonical_id));
const store = new MemoryIdentityStore(snapshot);
const writer = new StructuralIdentityWriter(store, async credential => ({ actor_id: credential, actor_kind: credential === "fixture-admin" ? "ADMIN" : "AI",
  can_propose: true, can_apply_structure: credential === "fixture-admin", r6_allowed: false }));
const beforeFull = structuralHash(store.state);
await assert.rejects(writer.submit("fixture-admin", batch("nine-atomic", input.candidates.map((c: any) => c.create_intent)), "APPLY"), /ATOMIC_VALIDATION_REJECTED/);
assert.equal(structuralHash(store.state), beforeFull);
const fakeResult = await writer.submit("fixture-admin", batch("valid-subset-fake-only", accepted.map((c: any) => c.create_intent)), "APPLY");
assert.equal(fakeResult.status, "APPLIED");
assert.equal(store.state.vehicle_models.length - snapshot.vehicle_models.length, accepted.length);
const beforeR6 = structuralHash(store.state);
await assert.rejects(writer.submit("fixture-admin", batch("links-denied", accepted.flatMap((c: any) => c.link_intents)), "APPLY"), /R6_AUTHORIZATION_DENIED/);
assert.equal(structuralHash(store.state), beforeR6);
await writer.submit("fixture-agent", batch("nine-proposal-only", input.candidates.map((c: any) => c.create_intent)), "PROPOSE");
assert.equal(store.state.ice_model_crosswalk_scoped.length, 0);
assert.equal(structuralHash(snapshot), initial);
const candidateUnits = candidates.reduce((n: number, c: any) => n + c.registrations, 0);
const validUnits = candidates.filter((c: any) => validIds.has(c.canonical_id)).reduce((n: number, c: any) => n + c.registrations, 0);
const denominator = input.source_reconciliation.effective_registrations;
const report = {
  schema: "tdr.structural-identity-writer.preflight.v1", source_pr: 235, source_commit: input.source_commit,
  catalog_captured_at_utc: input.catalog_captured_at_utc, catalog_model_rows_sha256: input.catalog_model_rows_sha256,
  snapshot_is_read_only_and_not_a_live_revision_read: true,
  source_files_sha256: input.source_files_sha256, source_reconciliation: input.source_reconciliation,
  frozen_owner_decisions: input.frozen_owner_decisions,
  counts: { requested_identities: candidates.length, requested_registrations: candidateUnits,
    valid_basic_identity_proposals: accepted.length, valid_proposal_registrations: validUnits,
    review_hold_identities: holds.length, review_hold_registrations: candidateUnits - validUnits },
  candidates,
  held_catalog_repair_candidates: holds.map((c: any) => ({ canonical_id: c.canonical_id,
    conflicting_catalog_id: "ford.ranger_double_cab", conflicting_alias: "ranger raptor",
    disposition: "REPAIR_REVIEW_HOLD_NOT_CREATE_AUTHORITY", owner_target_unchanged: true,
    missing_evidence: "Current row revision and reviewed alias-detach/equivalence plan; frozen target is not reopened." })),
  offline_transaction_simulation: { all_nine_batch_rejected_atomically: true, valid_subset_fake_created_rows: accepted.length,
    fake_audit_revisions: store.state.audit.length, r6_denied_with_zero_link_changes: true, no_production_store_or_adapter_used: true },
  weighted_readiness_simulation: { effective_denominator: denominator, existing_identity_candidate_registrations: input.existing_identity_candidate_registrations,
    valid_subset_candidate_registrations: validUnits, simulated_existing_plus_valid_subset_registrations: input.existing_identity_candidate_registrations + validUnits,
    simulated_existing_plus_valid_subset_pct: Number((100 * (input.existing_identity_candidate_registrations + validUnits) / denominator).toFixed(6)),
    target_pct: 99.1, meets_target_with_only_these_nine: (input.existing_identity_candidate_registrations + validUnits) / denominator >= 0.991 },
  production: { newly_approved_or_servable_registrations: 0, structural_database_adapter_present: false,
    migration_number_assigned: false, migrations_executed: false, r6_authorized: false,
    blockers: ["BASIC_IDENTITY_SCHEMA_CONTRACT_V57_V59", "STRUCTURAL_OBSERVATION_FIELDS_V66", "SERVER_AUTHENTICATED_STRUCTURAL_RPC_AND_ADAPTER", "SCOPED_LINK_SCHEMA_AND_REVISION_CONTRACT", "C02_MIGRATION_RECONCILIATION", "C01_R6_AUTHORIZATION"] },
};
assert.equal(candidateUnits, 59948); assert.equal(candidates.length, 9);
assert.equal(holds.length, 1); assert.equal(holds[0].canonical_id, "ford.ranger_raptor_double_cab");
assert.equal(report.frozen_owner_decisions.changed, 0); assert.equal(report.source_reconciliation.source_registrations, 4141987);
const encoded = JSON.stringify(report, null, 2) + "\n";
const path = `${directory}/nine_identity_preflight_report.json`;
if (process.argv.includes("--check")) assert.equal(fs.readFileSync(path, "utf8"), encoded, "Preflight evidence is stale");
else fs.writeFileSync(path, encoded);
console.log(JSON.stringify({ ...report.counts, coverage_simulation: report.weighted_readiness_simulation, production_approved_or_servable_additions: 0 }, null, 2));
