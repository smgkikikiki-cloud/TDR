import assert from "node:assert/strict";
import fs from "node:fs";
import { StructuralIdentityWriter, type Batch, type Intent, type Principal, type Snapshot } from "../lib/vehicle-engine/structural-writer.ts";
import { BasicIdentityDbAdapter, OWNER_SNAPSHOT_BASIC_CAPABILITIES, basicSchemaBlockers, buildStructuralRpcDraftRequest,
  type BasicSchemaCapability, type StructuralRpcTransport } from "../lib/vehicle-engine/basic-identity-db-compat.ts";
import { MemoryIdentityStore } from "./test-support/structural-identity-store.ts";

let passed = 0;
async function test(name: string, run: () => unknown) { await run(); passed++; console.log("ok " + name); }
const snapshot = (): Snapshot => ({ vehicle_brands: [{ canonical_id: "honda", name_en: "Honda", slug: "honda", aliases: [], revision: 1, deleted_at: null }],
  vehicle_models: [], ice_model_crosswalk_scoped: [], ice_scopes: [] });
const create: Intent = { operation: "CREATE_MODEL_BASIC", canonical_id: "honda.jazz", brand_id: "honda", name_en: "Jazz", expected_revision: 0,
  identity_evidence: { granularity: "MODEL", model_name: "Jazz", references: ["fixture:owner-evidence"] } };
const batch: Batch = { batch_id: "basic-fixture", reason: "offline compatibility fixture", source_ref: "fixture:basic-identity",
  observed_at: "2026-10-13T00:00:00Z", intents: [create] };
const authorize = async (credential: string): Promise<Principal> => ({ actor_id: credential, actor_kind: "ADMIN", can_propose: true,
  can_apply_structure: true, r6_allowed: false });

await test("owner snapshot reports precise BASIC schema blockers", () => {
  assert.deepEqual(basicSchemaBlockers(OWNER_SNAPSHOT_BASIC_CAPABILITIES), [
    "BASIC_MODEL_REQUIRED_COLUMNS_NOT_NULL", "BASIC_MODEL_LEVEL_AND_CATALOG_SERVING_FILTER_MISSING",
    "STRUCTURAL_OBSERVATION_FIELD_NOT_DEPLOYED", "GOVERNED_STRUCTURAL_RPC_NOT_DEPLOYED",
    "REVISION_LEDGER_REQUIRES_RETIRED_COMMAND_FK",
  ]);
});

await test("existing Structural Identity Writer simulates a BASIC identity without fabricating catalog facts", async () => {
  const store = new MemoryIdentityStore(snapshot());
  const writer = new StructuralIdentityWriter(store, authorize);
  const result = await writer.submit("admin-fixture", batch, "APPLY");
  assert.equal(result.status, "APPLIED");
  const model = store.state.vehicle_models[0];
  assert.equal(model.identity_level, "BASIC");
  assert.equal(model.status, null); assert.equal(model.generation_id, null); assert.equal(model.segment, null); assert.equal(model.body_type, null);
  assert.equal(model.retail_price_min, undefined); assert.equal(model.retail_price_max, undefined);
});

await test("serializer produces one atomic structural RPC envelope without client actor or approval flags", async () => {
  const evidenceBatch = { ...batch, raw_evidence: { source_text: "Honda Jazz", source_ref: "fixture:evidence" } };
  const writer = new StructuralIdentityWriter(new MemoryIdentityStore(snapshot()), authorize);
  const plan = (await writer.submit("admin-fixture", evidenceBatch, "PROPOSE")).plan;
  const request = buildStructuralRpcDraftRequest(evidenceBatch, plan);
  assert.equal(request.rpc, "vm_apply_structural_changes");
  assert.equal(request.contract_version, "basic-identity-draft-v1");
  assert.equal(request.expected_revisions[0].revision, 0);
  assert.equal(request.provenance.source_ref, batch.source_ref);
  assert.deepEqual(request.raw_evidence, evidenceBatch.raw_evidence);
  assert.equal("actor_kind" in request, false); assert.equal("approved" in request, false); assert.equal("r6_allowed" in request, false);
  assert.equal(JSON.stringify(request).includes("retail_price"), false);
});

await test("R6 crosswalk operations cannot enter the BASIC adapter envelope", async () => {
  const linkBatch: Batch = { ...batch, intents: [{ operation: "LINK_ICE_MODEL_GROUP_BY_REG_TYPE", canonical_id: "honda.jazz",
    model_group_id: "ice-g", reg_type_scope: "RY1", master_version: "M7.0", expected_revision: 0 }] };
  await assert.rejects(async () => buildStructuralRpcDraftRequest(linkBatch, { batch_hash: "hash", changes: [], holds: [], requires_r6: true }), /R6_LINK_OUTSIDE_BASIC_IDENTITY_ADAPTER/);
});

await test("held plans cannot be serialized as executable structural RPC work", () => {
  assert.throws(() => buildStructuralRpcDraftRequest(batch, { batch_hash: "hash", changes: [], holds: [{ index: 0, code: "HOLD", detail: "collision" }], requires_r6: false }), /STRUCTURAL_PLAN_HAS_HOLDS/);
});

await test("DB adapter is fail-closed even with admin-like transport and all hypothetical capabilities", async () => {
  const allReady: BasicSchemaCapability = { modelStatusNullable: true, modelServedAsOfNullable: true, modelSeedReleaseNullable: true,
    explicitIdentityLevel: true, basicExcludedFromCatalogServing: true, structuralObservationField: true, governedStructuralRpc: true,
    scopedCrosswalkTable: true, revisionCanRepresentStructuralWrite: true };
  let calls = 0;
  const transport: StructuralRpcTransport = { async call() { calls++; return { status: "APPLIED" }; } };
  const adapter = new BasicIdentityDbAdapter(allReady);
  await assert.rejects(adapter.submit(transport, { rpc: "vm_apply_structural_changes", contract_version: "basic-identity-draft-v1",
    batch_id: "test", payload_hash: "hash", expected_revisions: [], intents: [], provenance: { source_ref: "x", observed_at: "x", reason: "x", source_hash: "x" } }),
    /BASIC_IDENTITY_DB_APPLY_DISABLED:GOVERNANCE_NOT_ACTIVATED/);
  assert.equal(calls, 0);
});

await test("migration sources confirm v57/v58 incompatibility and v66 is not a structural RPC", () => {
  const v57 = fs.readFileSync("supabase/migration_v57_vehicle_master_tables.sql", "utf8");
  const v58 = fs.readFileSync("supabase/migration_v58_vehicle_serving_parity.sql", "utf8");
  const v66 = fs.readFileSync("supabase/migration_v66_vehicle_master_governed_writer.sql", "utf8");
  assert.match(v57, /status text not null check/); assert.match(v57, /served_as_of date not null/); assert.match(v57, /seed_release_id text not null/);
  assert.match(v58, /where m\.deleted_at is null/); assert.doesNotMatch(v58, /identity_level\s*=\s*'CATALOG'/i);
  assert.match(v66, /vm_apply_price_changes/); assert.doesNotMatch(v66, /vm_apply_structural_changes/);
  assert.match(v66, /field_key text not null check[\s\S]*?LIST_PRICE/); assert.doesNotMatch(v66, /STRUCTURAL_IDENTITY/);
});

console.log(`PASS: ${passed} BASIC identity DB compatibility checks`);
