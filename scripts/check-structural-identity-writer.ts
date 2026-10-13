import assert from "node:assert/strict";
import fs from "node:fs";
import { StructuralIdentityWriter, planStructuralChanges, type Batch, type Intent, type Principal,
  type Snapshot, normalizeModelIdentity, structuralHash } from "../lib/vehicle-engine/structural-writer.ts";
import { MemoryIdentityStore } from "./test-support/structural-identity-store.ts";
import { enqueueCanonicalModelShadow } from "../lib/canonical-write-shadow.ts";

let passed = 0;
async function test(name: string, run: () => unknown) { await run(); passed++; console.log("ok " + name); }
const base = (): Snapshot => ({ vehicle_brands: [{ canonical_id: "honda", name_en: "Honda", slug: "honda", aliases: [], revision: 1, deleted_at: null }], vehicle_models: [], ice_model_crosswalk_scoped: [], ice_scopes: [] });
const batch = (id: string, intents: Intent[], extra = {}): Batch => ({ batch_id: id, reason: "offline regression fixture", source_ref: "fixture:identity", observed_at: "2026-10-13T00:00:00Z", intents, ...extra });
const create = (id = "honda.jazz", name = "Jazz", brand = "honda"): Intent => ({ operation: "CREATE_MODEL_BASIC", canonical_id: id, brand_id: brand, name_en: name,
  expected_revision: 0, identity_evidence: { granularity: "MODEL", model_name: name, references: ["fixture:model evidence"] } });
const metadata = (id: string) => ({ batch_id: id, reason: "compensating test", source_ref: "fixture:revert", observed_at: "2026-10-13T01:00:00Z" });
const permissions = async (credential: string): Promise<Principal> => ({ actor_id: credential, actor_kind: credential.startsWith("admin") ? "ADMIN" : "AI", can_propose: credential !== "anon",
  can_apply_structure: true, r6_allowed: credential === "admin-r6-fixture" });
function setup(snapshot = base()) { const store = new MemoryIdentityStore(snapshot); return { store, writer: new StructuralIdentityWriter(store, permissions) }; }
const alias = (id: string, values: string[], revision: number): Intent => ({ operation: "UPDATE_MODEL_ALIAS", canonical_id: id, aliases: values, expected_revision: revision });
const link = (group = "jazz", scope = "RY1", target = "honda.jazz", revision = 0): Intent => ({ operation: "LINK_ICE_MODEL_GROUP_BY_REG_TYPE", canonical_id: target, model_group_id: group,
  reg_type_scope: scope, master_version: "7.0", decision_ref: "frozen-ref", source_hash: "a".repeat(64), expected_revision: revision });

await test("basic creation keeps UNKNOWN, no invented generation/spec/retail state", async () => {
  const { store, writer } = setup(); const request = batch("create", [create()], { raw_evidence: { segment: "D-segment", body_type: "Sedan" } });
  const frozen = structuralHash(request); const result = await writer.submit("admin", request, "APPLY");
  assert.equal(result.status, "APPLIED"); assert.equal(structuralHash(request), frozen);
  const model = store.state.vehicle_models[0]; assert.equal(model.segment, null); assert.equal(model.body_type, null);
  assert.equal(model.status, null); assert.equal(model.generation_id, null); assert.equal(model.identity_level, "BASIC");
  assert.equal(store.state.observations[0].raw.raw_evidence.segment, "D-segment");
  assert.equal(store.state.audit[0].topic, "catalog"); assert.equal(store.state.audit[0].actor_kind, "ADMIN");
});
await test("duplicate canonical ID and duplicate natural identity are rejected", async () => {
  const { store, writer } = setup(); await writer.submit("admin", batch("a", [create()]), "APPLY");
  await assert.rejects(writer.submit("admin", batch("b", [create()]), "APPLY"), /STALE_REVISION_OR_DUPLICATE_ID/);
  await assert.rejects(writer.submit("admin", batch("c", [create("honda.jazz2", "Honda JAZZ")]), "APPLY"), /IDENTITY_OR_ALIAS_COLLISION/);
  assert.equal(store.state.vehicle_models.length, 1);
});
await test("missing Brand FK, invalid composed ID and uncertain model-vs-trim are held", () => {
  assert.match(planStructuralChanges(base(), batch("missing", [create("nope.jazz", "Jazz", "nope")])).holds[0].detail, /MISSING_BRAND_FK/);
  assert.match(planStructuralChanges(base(), batch("bad-id", [create("toyota.jazz")])).holds[0].detail, /INVALID_MODEL_ID/);
  const uncertain = create(); uncertain.identity_evidence!.granularity = "TRIM";
  assert.match(planStructuralChanges(base(), batch("trim", [uncertain])).holds[0].detail, /UNCERTAIN_MODEL_VS_TRIM/);
});
await test("authenticated AI proposes; cannot apply, approve, revert or spoof actor JSON", async () => {
  const { store, writer } = setup(); const r = await writer.submit("ai", batch("ai", [create()]), "PROPOSE");
  assert.equal(r.status, "PROPOSED"); assert.equal(store.state.vehicle_models.length, 0);
  await assert.rejects(writer.submit("ai", batch("ai-apply", [create()]), "APPLY"), /ADMIN_ONLY/);
  await assert.rejects(writer.approve("ai", r.proposal_id!), /ADMIN_ONLY/);
  await assert.rejects(writer.revert("ai", "ai", metadata("ai-revert")), /ADMIN_ONLY/);
  await assert.rejects(writer.submit("ai", { ...batch("spoof", [create()]), actor_kind: "ADMIN" } as Batch, "PROPOSE"), /UNKNOWN_BATCH_FIELD/);
  await assert.rejects(writer.submit("anon", batch("anon", [create()]), "PROPOSE"), /FORBIDDEN/);
});
await test("alias collision rejects atomic apply including target name in another model", async () => {
  const { store, writer } = setup(); await writer.submit("admin", batch("models", [create(), create("honda.city", "City")]), "APPLY");
  await assert.rejects(writer.submit("admin", batch("bad-alias", [alias("honda.jazz", ["City"], 1)]), "APPLY"), /IDENTITY_OR_ALIAS_COLLISION/);
  assert.equal(store.state.vehicle_models[0].revision, 1);
});
await test("alias detach plus distinct model create can repair a conflict in one transaction", async () => {
  const initial = base(); initial.vehicle_models = [{ canonical_id: "honda.city", brand_id: "honda", name_en: "City", slug: "honda-city", revision: 2, aliases: ["Jazz"], payload: { aliases: ["Jazz"] } }];
  const { store, writer } = setup(initial);
  await writer.submit("admin", batch("repair", [create(), alias("honda.city", [], 2)]), "APPLY");
  assert.equal(store.state.vehicle_models.length, 2); assert.equal(store.state.audit.filter(r => r.batch_id === "repair").length, 2);
});
await test("new incompatible alias needs reviewed equivalence even if the other model is absent", async () => {
  const { writer } = setup(); await writer.submit("admin", batch("create-city", [create("honda.city", "City")]), "APPLY");
  await assert.rejects(writer.submit("admin", batch("wrong-unseen-alias", [alias("honda.city", ["Jazz"], 1)]), "APPLY"), /UNPROVEN_ALIAS_EQUIVALENCE/);
  const s = base(); s.approved_alias_equivalences = [{ model_id: "honda.jazz", alias: "Fit", reference: "tdr:reviewed-equivalence" }];
  const reviewed = setup(s); await reviewed.writer.submit("admin", batch("model", [create()]), "APPLY");
  await reviewed.writer.submit("admin", batch("approved-alias", [alias("honda.jazz", ["Fit"], 1)]), "APPLY");
  assert.deepEqual(reviewed.store.state.vehicle_models[0].aliases, ["Fit"]);
});
await test("stale revision rejects changes without observation/audit side effects", async () => {
  const { store, writer } = setup(); await writer.submit("admin", batch("a", [create()]), "APPLY");
  await writer.submit("admin", batch("b", [alias("honda.jazz", ["Honda Jazz"], 1)]), "APPLY");
  const before = structuralHash(store.state);
  await assert.rejects(writer.submit("admin", batch("stale", [alias("honda.jazz", [], 1)]), "APPLY"), /STALE_REVISION/);
  assert.equal(structuralHash(store.state), before);
});
await test("identical retry is idempotent; changed request under same key is denied", async () => {
  const { store, writer } = setup(); const b = batch("once", [create()]); await writer.submit("admin", b, "APPLY");
  assert.equal((await writer.submit("admin", b, "APPLY")).replay, true);
  assert.equal(store.state.audit.length, 1); assert.equal(store.state.observations.length, 1);
  await assert.rejects(writer.submit("admin", { ...b, reason: "changed" }, "APPLY"), /IDEMPOTENCY_KEY_REUSED/);
});
await test("serializable concurrent creates prevent races", async () => {
  const { store, writer } = setup(); const result = await Promise.allSettled([writer.submit("admin", batch("x", [create()]), "APPLY"), writer.submit("admin", batch("y", [create()]), "APPLY")]);
  assert.equal(result.filter(r => r.status === "fulfilled").length, 1); assert.equal(store.state.vehicle_models.length, 1);
});
await test("async request mutation cannot smuggle a scoped link past the R6 check", async () => {
  const s = base(); s.ice_scopes = [{ model_group_id: "jazz", reg_type_scope: "RY1", master_version: "7.0" }];
  const store = new MemoryIdentityStore(s);
  let release!: () => void;
  const pause = new Promise<void>(resolve => { release = resolve; });
  const writer = new StructuralIdentityWriter(store, async () => { await pause; return permissions("admin"); });
  const request = batch("frozen-request", [create()]);
  const applying = writer.submit("admin", request, "APPLY"); request.intents.push(link()); release();
  const result = await applying; assert.equal(result.status, "APPLIED"); assert.equal(result.plan.requires_r6, false);
  assert.equal(store.state.ice_model_crosswalk_scoped.length, 0);
});
await test("late transaction failure rolls back brand/model, evidence, audit and receipt", async () => {
  const { store, writer } = setup(); store.failOnWrite = 2; const before = structuralHash(store.state);
  const b = batch("rollback", [{ operation: "CREATE_BRAND", canonical_id: "new_brand", name_en: "New Brand", expected_revision: 0 }, create("new_brand.model", "Model", "new_brand")]);
  await assert.rejects(writer.submit("admin", b, "APPLY"), /INJECTED_TRANSACTION_FAILURE/); assert.equal(structuralHash(store.state), before);
});
await test("brand creation checks canonical ID/name/alias uniqueness", async () => {
  const { writer } = setup(); await assert.rejects(writer.submit("admin", batch("dup-brand", [{ operation: "CREATE_BRAND", canonical_id: "honda2", name_en: "HONDA", expected_revision: 0 }]), "APPLY"), /IDENTITY_OR_ALIAS_COLLISION/);
});
await test("revert logs compensating soft-hide; retries and double revert do not append duplicates", async () => {
  const { store, writer } = setup(); await writer.submit("admin", batch("original", [create()]), "APPLY");
  await writer.revert("admin", "original", metadata("revert")); assert.equal(store.state.vehicle_models.length, 1);
  assert.equal(store.state.vehicle_models[0].revision, 2); assert.ok(store.state.vehicle_models[0].deleted_at);
  assert.equal(store.state.audit[1].reverts_id, store.state.audit[0].id);
  assert.equal((await writer.revert("admin", "original", metadata("revert"))).replay, true);
  assert.equal((await writer.revert("admin", "original", metadata("revert-again"))).replay, true); assert.equal(store.state.audit.length, 2);
});
await test("alias revert preserves model fields and increments revision", async () => {
  const { store, writer } = setup(); await writer.submit("admin", batch("create", [create()]), "APPLY");
  await writer.submit("admin", batch("aliases", [alias("honda.jazz", ["Honda Jazz"], 1)]), "APPLY");
  await writer.revert("admin", "aliases", metadata("undo-alias"));
  assert.deepEqual(store.state.vehicle_models[0].aliases, []); assert.equal(store.state.vehicle_models[0].revision, 3);
  await assert.rejects(writer.revert("admin", "create", metadata("stale-revert")), /STALE_REVERT/);
});
await test("brand revert cannot hide a parent with a subsequently created model", async () => {
  const { store, writer } = setup(); await writer.submit("admin", batch("brand", [{ operation: "CREATE_BRAND", canonical_id: "new", name_en: "New", expected_revision: 0 }]), "APPLY");
  await writer.submit("admin", batch("model", [create("new.model", "Model", "new")]), "APPLY");
  await assert.rejects(writer.revert("admin", "brand", metadata("bad-revert")), /ACTIVE_MODEL_DEPENDENT/); assert.equal(store.state.vehicle_brands.find(r => r.canonical_id === "new")!.deleted_at, null);
});
await test("reverting a hide cannot restore a model beneath a hidden Brand", async () => {
  const { writer } = setup();
  await writer.submit("admin", batch("new-brand", [{ operation: "CREATE_BRAND", canonical_id: "new", name_en: "New", expected_revision: 0 }]), "APPLY");
  await writer.submit("admin", batch("new-model", [create("new.model", "Model", "new")]), "APPLY");
  await writer.revert("admin", "new-model", metadata("hide-model"));
  await writer.revert("admin", "new-brand", metadata("hide-brand"));
  await assert.rejects(writer.revert("admin", "hide-model", metadata("restore-model")), /REVERT_MISSING_ACTIVE_BRAND_FK/);
});
await test("R6 deny rejects whole mixed batch; proposal keeps links pending and cannot self-approve", async () => {
  const s = base(); s.ice_scopes = [{ model_group_id: "jazz", reg_type_scope: "RY1", master_version: "7.0" }];
  const { store, writer } = setup(s); const b = batch("mixed", [create(), link()]);
  await assert.rejects(writer.submit("admin", b, "APPLY"), /R6_AUTHORIZATION_DENIED/); assert.equal(store.state.vehicle_models.length, 0);
  const proposal = await writer.submit("ai", b, "PROPOSE"); assert.equal(proposal.plan.requires_r6, true);
  await assert.rejects(writer.approve("admin", proposal.proposal_id!), /R6_AUTHORIZATION_DENIED/);
});
await test("approved fake R6 links isolate actual class; ALL and missing source are rejected", async () => {
  const s = base(); s.ice_scopes = [{ model_group_id: "jazz", reg_type_scope: "RY1", master_version: "7.0" }, { model_group_id: "jazz", reg_type_scope: "RY3", master_version: "7.0" }, { model_group_id: "other", reg_type_scope: "RY1", master_version: "7.0" }];
  const { store, writer } = setup(s); await writer.submit("admin-r6-fixture", batch("models", [create(), create("honda.other", "Other")]), "APPLY");
  await writer.submit("admin-r6-fixture", batch("links", [link(), link("jazz", "RY3", "honda.other"), link("other", "RY1")]), "APPLY");
  assert.equal(store.state.ice_model_crosswalk_scoped.length, 3); assert.equal(store.state.ice_model_crosswalk_scoped.find(r => r.reg_type_scope === "รย.3")!.canonical_model_id, "honda.other");
  assert.match(planStructuralChanges(store.state, batch("all", [link("jazz", "ALL")])).holds[0].detail, /CLASS_SCOPE_REQUIRED/);
  assert.match(planStructuralChanges(store.state, batch("bad-source", [link("missing", "RY1")])).holds[0].detail, /UNKNOWN_OR_STALE/);
  await assert.rejects(writer.revert("admin", "links", metadata("undo-links")), /R6_AUTHORIZATION_DENIED/);
});
await test("frozen owner scoped target/exclusion cannot be overwritten", async () => {
  const s = base(); s.ice_scopes = [{ model_group_id: "jazz", reg_type_scope: "RY1", master_version: "7.0", frozen_status: "EXCLUDED", decision_ref: "frozen-ref" }];
  const { store, writer } = setup(s); await writer.submit("admin", batch("models", [create()]), "APPLY");
  assert.match(planStructuralChanges(store.state, batch("frozen", [link()])).holds[0].detail, /FROZEN_OWNER_DECISION_CONFLICT/);
});
await test("revert cannot restore an old mapping that contradicts a frozen owner target", async () => {
  const s = base(); s.ice_scopes = [{ model_group_id: "jazz", reg_type_scope: "RY1", master_version: "7.0", frozen_status: "APPROVED", frozen_target_id: "honda.jazz", decision_ref: "frozen-ref" }];
  const { store, writer } = setup(s);
  await writer.submit("admin", batch("two-models", [create(), create("honda.other", "Other")]), "APPLY");
  store.state.ice_model_crosswalk_scoped = [{ model_group_id: "jazz", reg_type_scope: "รย.1", master_version: "7.0", canonical_model_id: "honda.other", status: "APPROVED", decision_ref: "frozen-ref", source_hash: "a".repeat(64), revision: 1 }];
  await writer.submit("admin-r6-fixture", batch("repair-frozen", [link("jazz", "RY1", "honda.jazz", 1)]), "APPLY");
  await assert.rejects(writer.revert("admin-r6-fixture", "repair-frozen", metadata("unsafe-undo")), /FROZEN_OWNER_REVERT_CONFLICT/);
  assert.equal(store.state.ice_model_crosswalk_scoped[0].canonical_model_id, "honda.jazz");
});
await test("approved TDR classifications win; Ice cannot set canonical fields", () => {
  const s = base(); s.tdr_classifications = [{ canonical_id: "honda.jazz", segment: "B", body_type: "HATCHBACK", evidence_ref: "tdr:approved-specific-identity" }];
  const p = planStructuralChanges(s, batch("classified", [create()], { raw_evidence: { segment: "D", body_type: "Sedan" } }));
  assert.equal(p.changes[0].after.segment, "B"); assert.equal(p.changes[0].after.body_type, "HATCHBACK");
  assert.match(planStructuralChanges(base(), batch("spoof-classification", [{ ...create(), segment: "D" } as Intent])).holds[0].detail, /UNKNOWN_INTENT_FIELD/);
});
await test("registration-class candidate cannot duplicate a current parent alias", () => {
  const s = base(); s.vehicle_brands = [{ canonical_id: "ford", name_en: "Ford", slug: "ford", revision: 1 }];
  s.vehicle_models = [{ canonical_id: "ford.ranger_double_cab", brand_id: "ford", name_en: "Ranger Double Cab", aliases: ["ranger raptor"], slug: "ford-ranger", revision: 1 }];
  const i = create("ford.ranger_raptor_double_cab", "Ranger Raptor Double Cab", "ford"); i.identity_evidence!.granularity = "MODEL_REGISTRATION_CLASS";
  assert.match(planStructuralChanges(s, batch("raptor", [i])).holds[0].detail, /REGISTRATION_CLASS_PARENT_ALIAS_CONFLICT/);
});
await test("approve recomputes current state and is idempotent", async () => {
  const { store, writer } = setup(); const p = await writer.submit("ai", batch("suggest", [create()]), "PROPOSE");
  await writer.approve("admin", p.proposal_id!); assert.equal(store.state.inbox[0].status, "APPROVED");
  assert.equal((await writer.approve("admin", p.proposal_id!)).replay, true);
  const other = setup(); const q = await other.writer.submit("ai", batch("suggest2", [create()]), "PROPOSE");
  await other.writer.submit("admin", batch("intervening", [create()]), "APPLY");
  await assert.rejects(other.writer.approve("admin", q.proposal_id!), /ATOMIC_VALIDATION_REJECTED/); assert.equal(other.store.state.inbox[0].status, "OPEN");
});
await test("rejected proposal is suppressed until the actual source content changes", async () => {
  const { store, writer } = setup(); await writer.submit("ai", batch("proposal-1", [create()]), "PROPOSE");
  store.state.inbox[0].status = "REJECTED"; // Simulated existing admin inbox decision.
  const again = await writer.submit("ai", batch("proposal-2", [create()]), "PROPOSE");
  assert.equal(again.status, "SUPPRESSED"); assert.equal(store.state.inbox.length, 1);
  const changed = create(); changed.identity_evidence!.references.push("new-source-content");
  assert.equal((await writer.submit("ai", batch("proposal-3", [changed]), "PROPOSE")).status, "PROPOSED");
  assert.equal(store.state.inbox.length, 2);
});
await test("identity letters and numbers are not trim-normalized away", () => {
  assert.notEqual(normalizeModelIdentity("6e"), normalizeModelIdentity("6")); assert.notEqual(normalizeModelIdentity("S3"), normalizeModelIdentity("A3"));
  assert.notEqual(normalizeModelIdentity("Atto 1"), normalizeModelIdentity("Atto 2")); assert.notEqual(normalizeModelIdentity("530e"), normalizeModelIdentity("5 Series"));
});
await test("retired shadow compatibility guard cannot enqueue", async () => {
  assert.deepEqual(await enqueueCanonicalModelShadow({ sourceModelId: "old", payload: { model: {}, powertrains: [], trims: [] } }), { enqueued: false, status: "disabled", canonicalId: null });
  assert.doesNotMatch(fs.readFileSync("lib/canonical-write-shadow.ts", "utf8"), /adminDb|\.insert\(|\.rpc\(/);
});
console.log(`${passed} structural identity writer tests passed (fake store only; no production authorization)`);
