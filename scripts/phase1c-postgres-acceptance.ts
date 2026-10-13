/** Real local PostgreSQL acceptance for the unnumbered Phase 1C DDL.
 * Starts a disposable Docker container on --network none with tmpfs-only PGDATA.
 * Never reads DB connection URLs and never targets a shared server. */
import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { planStructuralChanges, structuralHash, type Batch, type Snapshot } from "../lib/vehicle-engine/structural-writer.ts";
import { buildStructuralRpcDraftRequest, type StructuralRpcDraftRequest } from "../lib/vehicle-engine/basic-identity-db-compat.ts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = "postgres:16.10-alpine@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297";
const name = `tdr-phase1c-${process.pid}`;
const user = "phase1c_owner";
const rpcUser = "phase1c_rpc_actor";
const database = "phase1c_acceptance";
const tmpSecret = randomBytes(32).toString("hex");
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
function run(cmd: string, args: string[], input?: string, allowFailure = false): string {
  const result = spawnSync(cmd, args, { cwd: root, input, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0 && !allowFailure) throw new Error(`${cmd} failed (${result.status}): ${result.stderr || result.stdout}`);
  return `${result.stdout}${result.stderr}`.trim();
}
function pg(sql: string): string {
  return run("docker", ["exec", "-i", name, "psql", "-X", "-U", user, "-d", database, "-v", "ON_ERROR_STOP=1", "-At", "-P", "pager=off"], sql);
}
function pgAsRpcActor(sql: string): string {
  return run("docker", ["exec", "-i", name, "psql", "-X", "-U", rpcUser, "-d", database, "-v", "ON_ERROR_STOP=1", "-At", "-P", "pager=off"], sql);
}
function expectPgFailure(sql: string, expected: string): void {
  const output = run("docker", ["exec", "-i", name, "psql", "-X", "-U", user, "-d", database, "-v", "ON_ERROR_STOP=1", "-At"], sql, true);
  assert.match(output, new RegExp(expected));
}
function expectLoginRoleFailure(login: string, sql: string, expected: string): void {
  const output = run("docker", ["exec", "-i", name, "psql", "-X", "-U", login, "-d", database, "-v", "ON_ERROR_STOP=1", "-At"], sql, true);
  assert.match(output, new RegExp(expected));
}
const quote = (s: string) => `'${s.replaceAll("'", "''")}'`;
function rpcSql(request: StructuralRpcDraftRequest, token: string): string {
  const encoded = Buffer.from(JSON.stringify(request)).toString("base64");
  return `BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(convert_from(decode('${encoded}','base64'),'UTF8')::jsonb,${quote(token)}); COMMIT;`;
}
function rpc(request: StructuralRpcDraftRequest, token: string): string {
  return pgAsRpcActor(rpcSql(request, token));
}
function rpcConcurrent(request: StructuralRpcDraftRequest, token: string): Promise<{ status: number | null; output: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn("docker", ["exec", "-i", name, "psql", "-X", "-U", rpcUser, "-d", database, "-v", "ON_ERROR_STOP=1", "-At", "-P", "pager=off"]);
    let output = "";
    child.stdout.setEncoding("utf8").on("data", (chunk) => output += chunk);
    child.stderr.setEncoding("utf8").on("data", (chunk) => output += chunk);
    child.on("error", reject);
    child.on("close", (status) => resolve({ status, output }));
    child.stdin.end(rpcSql(request, token));
  });
}
function revertRpc(revisionId: string, expectedRevision: number, token: string): string {
  return pgAsRpcActor(`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_revert_structural_revision(${quote(revisionId)}::uuid,${expectedRevision},${quote(token)}); COMMIT;`);
}
function parseRpcResult(output: string): any {
  const line = output.split("\n").find((value) => value.startsWith("{"));
  assert.ok(line, `RPC returned no JSON result: ${output}`);
  return JSON.parse(line);
}
function createRequest(candidateIntents: Batch["intents"], id = "phase1c-eight-valid-identities", rawEvidence?: Record<string, unknown>): { batch: Batch; request: StructuralRpcDraftRequest } {
  const batch: Batch = { batch_id: id, reason: "Issue 240 isolated PostgreSQL acceptance; candidate test only", source_ref: "frozen-preflight:2026-10-13", observed_at: "2026-10-13T00:00:00.000Z", intents: candidateIntents,
    ...(rawEvidence === undefined ? {} : { raw_evidence: rawEvidence }) };
  const plan = planStructuralChanges(snapshot, batch);
  assert.equal(plan.holds.length, 0, JSON.stringify(plan.holds));
  assert.equal(plan.changes.length, candidateIntents.length);
  return { batch, request: buildStructuralRpcDraftRequest(batch, plan) };
}

const ledgerPath = "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/owner_decision_ledger_244.csv";
const snapshotPath = "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/vehicle_master_identity_snapshot_2026-10-13.json";
const inputsPath = "docs/vehicle-db/structural-writer/nine_identity_inputs.json";
const preflightPath = "docs/vehicle-db/structural-writer/nine_identity_preflight_report.json";
const preflight = JSON.parse(fs.readFileSync(path.join(root, preflightPath), "utf8"));
const nineInputs = JSON.parse(fs.readFileSync(path.join(root, inputsPath), "utf8"));
const frozenLedgerHash = "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8";
const frozenSnapshotHash = "cf991264ada90efb0ff69a754cdee11fb0d13cc98fbe9fc60879de4eb7a2eb62";
assert.equal(sha(fs.readFileSync(path.join(root, ledgerPath), "utf8")), frozenLedgerHash);
assert.equal(sha(fs.readFileSync(path.join(root, snapshotPath), "utf8")), frozenSnapshotHash);
assert.equal(preflight.frozen_owner_decisions.total, 244);
assert.equal(preflight.frozen_owner_decisions.changed, 0);
assert.equal(preflight.frozen_owner_decisions.reopened, 0);
const validated = preflight.candidates.filter((x: any) => x.disposition === "VALID_BASIC_IDENTITY_PROPOSAL");
const held = preflight.candidates.filter((x: any) => x.canonical_id === "ford.ranger_raptor_double_cab");
assert.equal(validated.length, 8);
assert.equal(validated.reduce((s: number, x: any) => s + x.registrations, 0), 47109);
assert.equal(held.length, 1);
assert.equal(held[0].disposition, "REVIEW_HOLD");
assert.match(held[0].holds[0].detail, /REGISTRATION_CLASS_PARENT_ALIAS_CONFLICT:ford\.ranger_double_cab/);

const sourceSnapshot = JSON.parse(fs.readFileSync(path.join(root, snapshotPath), "utf8"));
const brandRows = sourceSnapshot.relations.vehicle_brands.rows;
const modelRows = sourceSnapshot.relations.vehicle_models.rows;
const snapshot: Snapshot = {
  vehicle_brands: brandRows.map((r: any) => ({ ...r, revision: 1, deleted_at: null })),
  vehicle_models: modelRows.map((r: any) => ({ ...r, revision: 1, deleted_at: null })),
  ice_model_crosswalk_scoped: [], ice_scopes: [],
};
const inputById = new Map(nineInputs.candidates.map((x: any) => [x.canonical_id, x]));
const createIntents = validated.map((candidate: any) => (inputById.get(candidate.canonical_id) as any).create_intent);
const rawIceEvidence = Object.assign({}, ...validated.map((candidate: any) => candidate.raw_ice_classification_evidence));
assert.equal(Object.keys(rawIceEvidence).length, 8);
const { batch, request } = createRequest(createIntents, "phase1c-eight-valid-identities", rawIceEvidence);

try {
  run("docker", ["run", "--detach", "--rm", "--name", name, "--network", "none", "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=1g",
    "--env", `POSTGRES_PASSWORD=${tmpSecret}`, "--env", `POSTGRES_USER=${user}`, "--env", "POSTGRES_DB=postgres", image]);
  let ready = false;
  for (let i = 0; i < 60; i++) {
    // The official image starts a socket-only bootstrap server before the
    // final server. Require loopback TCP readiness, which only the final
    // disposable server exposes inside its network-isolated container.
    const output = run("docker", ["exec", name, "pg_isready", "-h", "127.0.0.1", "-U", user, "-d", "postgres"], undefined, true);
    if (output.includes("accepting connections")) { ready = true; break; }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500);
  }
  assert.ok(ready, "isolated PostgreSQL did not start");
  run("docker", ["exec", name, "createdb", "-U", user, database]);
  const files = [
    "docs/vehicle-db/drafts/phase1c/bootstrap_supabase_test_support.sql",
    "supabase/migration_v12_canonical_write_pipeline.sql", "supabase/migration_v15_canonical_vehicle_release.sql",
    "supabase/migration_v22_unified_vehicle_input.sql", "supabase/migration_v48_staged_vehicle_release.sql",
    "supabase/migration_v57_vehicle_master_tables.sql", "docs/vehicle-db/drafts/phase1c/seed_catalog_parity.sql",
    "supabase/migration_v58_vehicle_serving_parity.sql", "supabase/migration_v59_vehicle_engine_rules.sql",
    "supabase/migration_v60_close_legacy_vehicle_write_path.sql", "supabase/migration_v61_vehicle_master_backups_bucket.sql",
    "supabase/migration_v62_ice_market_panels.sql", "supabase/migration_v63_ice_model_crosswalk.sql",
    "supabase/migration_v64_ice_panel_grain_fix.sql", "docs/vehicle-db/drafts/phase1c/basic_identity_schema.sql",
    "docs/vehicle-db/drafts/phase1c/governed_structural_rpc.sql",
  ];
  for (const file of files) pg(fs.readFileSync(path.join(root, file), "utf8"));
  const dbVersion = pg("SELECT current_setting('server_version')");
  assert.equal(dbVersion, "16.10");
  assert.equal(pg("SELECT has_function_privilege('vm_structural_rpc_owner','public._vm_structure_problems(text)','EXECUTE')"),"t");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_serving_parity_check() WHERE NOT ok"), "0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_master_seed_check() WHERE NOT ok"), "0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_engine_rules_check()"), "0");
  expectPgFailure("SET ROLE authenticated; INSERT INTO public.vehicle_models(canonical_id,brand_id,slug,name_en,payload,identity_level,identity_aliases) VALUES ('honda.forbidden','honda','honda-forbidden','Forbidden','{}','BASIC','[]');",
    "permission denied|row-level security|new row violates");
  expectPgFailure("SET ROLE service_role; SELECT vehicle_private.vm_apply_structural_changes('{}'::jsonb,'no-capability');", "permission denied for (schema|function) vehicle_private|vm_apply_structural_changes");

  // Test fixture identity rows are copied only from the frozen owner snapshot;
  // tokens from every row are loaded to make database collision checks meaningful.
  const candidateBrandIds = [...new Set(createIntents.map((x: any) => x.brand_id))];
  const fixtureBrands = brandRows.filter((b: any) => candidateBrandIds.includes(b.canonical_id) && b.canonical_id !== "toyota");
  assert.equal(fixtureBrands.length, candidateBrandIds.length - 1);
  const brandValues = fixtureBrands.map((b: any) => `(${quote(b.canonical_id)},${quote(b.slug)},${quote(b.name_en)},${b.name_th == null ? "NULL" : quote(b.name_th)},
    ${quote(JSON.stringify({ id: b.canonical_id, name_en: b.name_en, aliases: b.aliases || [], identity_level: "BASIC", incomplete: true }))}::jsonb,NULL,1,NULL,'BASIC',${quote(JSON.stringify(b.aliases || []))}::jsonb)`).join(",\n");
  const tokenRows: string[] = [];
  for (const b of brandRows) for (const raw of [b.name_en,b.name_th,...(b.aliases||[])]) if (raw) tokenRows.push(`('BRAND','',${quote(b.canonical_id)},vehicle_private.vm_identity_normalize(${quote(raw)},''),'LOCAL_READONLY_SNAPSHOT',${quote(frozenSnapshotHash)})`);
  for (const m of modelRows) {
    const brand = brandRows.find((b: any) => b.canonical_id === m.brand_id);
    for (const raw of [m.name_en,m.name_th,...(m.aliases||[])]) if (raw) tokenRows.push(`('MODEL',${quote(m.brand_id)},${quote(m.canonical_id)},vehicle_private.vm_identity_normalize(${quote(raw)},${quote(brand?.name_en||"")}),'LOCAL_READONLY_SNAPSHOT',${quote(frozenSnapshotHash)})`);
  }
  pg(`INSERT INTO public.vehicle_brands(canonical_id,slug,name_en,name_th,payload,served_as_of,revision,seed_release_id,identity_level,identity_aliases) VALUES ${brandValues};
      INSERT INTO vehicle_private.vm_identity_tokens(entity_type,brand_id,canonical_id,normalized_token,source_kind,source_snapshot_sha256) VALUES ${tokenRows.join(",\n")} ON CONFLICT DO NOTHING;
      CREATE ROLE phase1c_rpc_actor LOGIN;
      CREATE ROLE phase1c_unprivileged LOGIN;
      GRANT vm_structural_approver,vm_structural_approval_admin TO phase1c_rpc_actor;`);
  expectLoginRoleFailure("phase1c_unprivileged", "SELECT vehicle_private.vm_apply_structural_changes('{}'::jsonb,'no-capability');",
    "permission denied for schema vehicle_private");
  expectLoginRoleFailure("phase1c_unprivileged", "INSERT INTO public.vehicle_models(canonical_id,brand_id,slug,name_en,payload,identity_level,identity_aliases) VALUES ('honda.unprivileged','honda','honda-unprivileged','Unprivileged','{}','BASIC','[]');",
    "permission denied|row-level security|new row violates");

  // The second insert raises after the first identity has been written inside
  // the RPC. PostgreSQL must roll back the whole identity/audit/receipt unit.
  pg(`CREATE FUNCTION vehicle_private.phase1c_injected_failure() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.canonical_id='honda.phase1c_atomic_two' THEN RAISE EXCEPTION 'PHASE1C_INJECTED_FAILURE'; END IF; RETURN NEW; END $$;
      CREATE TRIGGER phase1c_injected_failure BEFORE INSERT ON public.vehicle_models FOR EACH ROW EXECUTE FUNCTION vehicle_private.phase1c_injected_failure();`);
  const atomicIntents = [
    { operation: "CREATE_MODEL_BASIC", canonical_id: "honda.phase1c_atomic_one", brand_id: "honda", name_en: "Phase1C Atomic One", expected_revision: 0,
      identity_evidence: { granularity: "MODEL", model_name: "Phase1C Atomic One", references: ["fixture:atomic-one"] } },
    { operation: "CREATE_MODEL_BASIC", canonical_id: "honda.phase1c_atomic_two", brand_id: "honda", name_en: "Phase1C Atomic Two", expected_revision: 0,
      identity_evidence: { granularity: "MODEL", model_name: "Phase1C Atomic Two", references: ["fixture:atomic-two"] } },
  ] as Batch["intents"];
  const atomic = createRequest(atomicIntents, "phase1c-injected-rollback");
  const atomicToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-rollback',${quote(atomic.request.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(atomicToken)});`);
  assert.equal(pgAsRpcActor("SELECT session_user"),rpcUser);
  const atomicCapability = pg(`SELECT principal||'|'||batch_hash||'|'||array_to_string(operations,',')||'|'||(expires_at>clock_timestamp())::text||'|'||(consumed_at IS NULL)::text FROM vehicle_private.vm_structural_capabilities WHERE token_sha256=public.digest(${quote(atomicToken)},'sha256')`);
  assert.equal(atomicCapability,`${rpcUser}|${atomic.request.batch_hash}|CREATE_MODEL_BASIC|true|true`);
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(atomic.request))}::jsonb,${quote(atomicToken)}); COMMIT;`, "PHASE1C_INJECTED_FAILURE");
  pg("DROP TRIGGER phase1c_injected_failure ON public.vehicle_models; DROP FUNCTION vehicle_private.phase1c_injected_failure();");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE canonical_id IN ('honda.phase1c_atomic_one','honda.phase1c_atomic_two')"), "0");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_observations WHERE batch_id='phase1c-injected-rollback'"), "0");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_revisions WHERE batch_id='phase1c-injected-rollback'"), "0");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_receipts WHERE batch_id='phase1c-injected-rollback'"), "0");

  const token = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability(${quote("phase1c-approved-eight")},${quote(request.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(token)});`);
  const applied = parseRpcResult(rpc(request, token));
  assert.equal(applied.status, "APPLIED");
  assert.equal(applied.revision_ids.length, 8);
  const replay = parseRpcResult(rpc(request, token));
  assert.equal(replay.replay, true);
  const changedBatch: Batch = { ...batch, reason: "changed payload under the same idempotency key" };
  const changedRequest = buildStructuralRpcDraftRequest(changedBatch, planStructuralChanges(snapshot, changedBatch));
  const changedToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-changed-retry',${quote(changedRequest.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(changedToken)});`);
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(changedRequest))}::jsonb,${quote(changedToken)}); COMMIT;`, "STRUCTURAL_IDEMPOTENCY_HASH_CONFLICT");

  const collisionBatch = createRequest([createIntents.find((i: any) => i.canonical_id === "honda.jazz") as any], "phase1c-canonical-collision");
  const collisionToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-canonical-collision',${quote(collisionBatch.request.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(collisionToken)});`);
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(collisionBatch.request))}::jsonb,${quote(collisionToken)}); COMMIT;`, "STRUCTURAL_CANONICAL_OR_SLUG_COLLISION");
  const aliasCollisionIntent: any = { operation: "CREATE_MODEL_BASIC", canonical_id: "honda.phase1c_jazz_alias", brand_id: "honda", name_en: "Phase1C Jazz Alias",
    expected_revision: 0, identity_evidence: { granularity: "MODEL", model_name: "Phase1C Jazz Alias", references: ["fixture:alias-collision"] } };
  const aliasCollision = createRequest([aliasCollisionIntent], "phase1c-alias-collision");
  // Deliberately bypass the TypeScript planner after constructing a valid
  // envelope: the database itself must catch a normalized alias collision.
  aliasCollision.request.intents[0].aliases = ["Jazz"];
  aliasCollision.request.provenance.source_hash = structuralHash({ source_ref: aliasCollision.batch.source_ref, raw_evidence: null,
    intents: aliasCollision.request.intents.map(({ expected_revision: _revision, ...intent }) => intent) });
  aliasCollision.request.batch_hash = structuralHash({ ...aliasCollision.batch, intents: aliasCollision.request.intents });
  const { payload_hash: _oldCollisionHash, ...collisionEnvelope } = aliasCollision.request;
  aliasCollision.request.payload_hash = structuralHash(collisionEnvelope);
  pg("INSERT INTO vehicle_private.vm_approved_alias_equivalences(model_id,normalized_alias,source_ref,approved_by) VALUES ('honda.phase1c_jazz_alias',vehicle_private.vm_identity_normalize('Jazz','Honda'),'fixture:Phase1C collision assertion','phase1c-test-approver')");
  const aliasCollisionToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-alias-collision',${quote(aliasCollision.request.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(aliasCollisionToken)});`);
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(aliasCollision.request))}::jsonb,${quote(aliasCollisionToken)}); COMMIT;`, "STRUCTURAL_NORMALIZED_IDENTITY_COLLISION");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE identity_level='BASIC'"), "8");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE identity_level='BASIC' AND (status IS NOT NULL OR generation_id IS NOT NULL OR served_as_of IS NOT NULL OR seed_release_id IS NOT NULL OR segment IS NOT NULL OR body_type IS NOT NULL OR retail_price_min IS NOT NULL OR retail_price_max IS NOT NULL)"), "0");
  assert.equal(pg("SELECT count(*) FROM public.current_vehicle_models"), "1");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.market_analysis_basic_identities"), "8");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_observations WHERE batch_id='phase1c-eight-valid-identities'"), "1");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_observations o CROSS JOIN LATERAL jsonb_each(o.raw_evidence) e WHERE o.batch_id='phase1c-eight-valid-identities' AND e.value ? 'body' AND e.value ? 'segment'"), "8");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_revisions WHERE batch_id='phase1c-eight-valid-identities'"), "8");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_receipts WHERE batch_id='phase1c-eight-valid-identities'"), "1");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_serving_parity_check() WHERE NOT ok"), "0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_master_seed_check() WHERE NOT ok"), "0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_engine_rules_check()"), "0");

  // A stale alias preview built from the supplied frozen snapshot cannot
  // overwrite a row that now has revision 1 in the isolated master.
  const jazzIntent = createIntents.find((i: any) => i.canonical_id === "honda.jazz") as any;
  const jazzRow: any = { canonical_id: jazzIntent.canonical_id, brand_id: jazzIntent.brand_id, name_en: jazzIntent.name_en,
    slug: "honda-jazz", aliases: [], revision: 0, deleted_at: null, identity_level: "BASIC", status: null, generation_id: null,
    segment: null, body_type: null, payload: { id: jazzIntent.canonical_id, brand_id: jazzIntent.brand_id, name_en: jazzIntent.name_en,
      aliases: [], identity_level: "BASIC", incomplete: true } };
  const staleSnapshot = structuredClone(snapshot); staleSnapshot.vehicle_models.push(jazzRow);
  const staleBatch: Batch = { batch_id: "phase1c-stale-alias", reason: "stale CAS check", source_ref: "fixture:stale-alias",
    observed_at: "2026-10-13T00:01:00.000Z", intents: [{ operation: "UPDATE_MODEL_ALIAS", canonical_id: "honda.jazz", aliases: ["Jazz"], expected_revision: 0 }] };
  const staleRequest = buildStructuralRpcDraftRequest(staleBatch, planStructuralChanges(staleSnapshot, staleBatch));
  const staleToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-stale-alias',${quote(staleRequest.batch_hash)},ARRAY['UPDATE_MODEL_ALIAS'],now()+interval '5 minutes',${quote(staleToken)});`);
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(staleRequest))}::jsonb,${quote(staleToken)}); COMMIT;`, "STRUCTURAL_STALE_REVISION");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_observations WHERE batch_id='phase1c-stale-alias'"), "0");
  const expiredToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-expired-alias',${quote(staleRequest.batch_hash)},ARRAY['UPDATE_MODEL_ALIAS'],now()+interval '1 second',${quote(expiredToken)});`);
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1100);
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(staleRequest))}::jsonb,${quote(expiredToken)}); COMMIT;`, "STRUCTURAL_CAPABILITY_EXPIRED");
  const currentSnapshot = structuredClone(snapshot); currentSnapshot.vehicle_models.push({ ...jazzRow, revision: 1 });
  const aliasBatch: Batch = { ...staleBatch, batch_id: "phase1c-valid-alias", reason: "alias CAS check",
    intents: [{ ...staleBatch.intents[0], expected_revision: 1 }] };
  const aliasRequest = buildStructuralRpcDraftRequest(aliasBatch, planStructuralChanges(currentSnapshot, aliasBatch));
  const aliasToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-valid-alias',${quote(aliasRequest.batch_hash)},ARRAY['UPDATE_MODEL_ALIAS'],now()+interval '5 minutes',${quote(aliasToken)});`);
  assert.equal(parseRpcResult(rpc(aliasRequest, aliasToken)).status, "APPLIED");
  assert.equal(pg("SELECT revision FROM public.vehicle_models WHERE canonical_id='honda.jazz'"), "2");
  const aliasRevision = pg("SELECT revision_id FROM vehicle_private.vm_structural_revisions WHERE batch_id='phase1c-valid-alias'");
  const revertHash = structuralHash({ operation: "REVERT", revision_id: aliasRevision, expected_revision: 2 });
  const revertToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-alias-revert',${quote(revertHash)},ARRAY['REVERT'],now()+interval '5 minutes',${quote(revertToken)});`);
  assert.equal(parseRpcResult(revertRpc(aliasRevision, 2, revertToken)).status, "REVERTED");
  assert.equal(parseRpcResult(revertRpc(aliasRevision, 2, revertToken)).replay, true);
  assert.equal(pg("SELECT revision FROM public.vehicle_models WHERE canonical_id='honda.jazz'"), "3");
  assert.equal(pg("SELECT identity_aliases::text FROM public.vehicle_models WHERE canonical_id='honda.jazz'"), "[]");

  // Revert-created identities are soft-hidden. A brand with an active model is
  // protected, and becomes reversible only after the child is hidden first.
  const brandBatch: Batch = { batch_id: "phase1c-revert-brand", reason: "revert dependency fixture", source_ref: "fixture:revert-brand",
    observed_at: "2026-10-13T00:02:00.000Z", intents: [{ operation: "CREATE_BRAND", canonical_id: "phase1c_revert_brand",
      name_en: "Phase1C Revert Brand", expected_revision: 0 }] };
  const brandRequest = buildStructuralRpcDraftRequest(brandBatch, planStructuralChanges(snapshot, brandBatch));
  const brandToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-brand-create',${quote(brandRequest.batch_hash)},ARRAY['CREATE_BRAND'],now()+interval '5 minutes',${quote(brandToken)});`);
  assert.equal(parseRpcResult(rpc(brandRequest, brandToken)).status, "APPLIED");
  const brandRevision = pg("SELECT revision_id FROM vehicle_private.vm_structural_revisions WHERE batch_id='phase1c-revert-brand'");
  const brandRow = { canonical_id: "phase1c_revert_brand", slug: "phase1c_revert_brand", name_en: "Phase1C Revert Brand", aliases: [],
    revision: 1, deleted_at: null, identity_level: "BASIC", payload: { id: "phase1c_revert_brand", name_en: "Phase1C Revert Brand", aliases: [], identity_level: "BASIC", incomplete: true } };
  const dependentSnapshot = structuredClone(snapshot); dependentSnapshot.vehicle_brands.push(brandRow);
  const dependentBatch: Batch = { batch_id: "phase1c-revert-child", reason: "revert dependency fixture", source_ref: "fixture:revert-child",
    observed_at: "2026-10-13T00:03:00.000Z", intents: [{ operation: "CREATE_MODEL_BASIC", canonical_id: "phase1c_revert_brand.test_model",
      brand_id: "phase1c_revert_brand", name_en: "Test Model", expected_revision: 0,
      identity_evidence: { granularity: "MODEL", model_name: "Test Model", references: ["fixture:revert-child"] } }] };
  const dependentRequest = buildStructuralRpcDraftRequest(dependentBatch, planStructuralChanges(dependentSnapshot, dependentBatch));
  const dependentToken = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-child-create',${quote(dependentRequest.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(dependentToken)});`);
  assert.equal(parseRpcResult(rpc(dependentRequest, dependentToken)).status, "APPLIED");
  const childRevision = pg("SELECT revision_id FROM vehicle_private.vm_structural_revisions WHERE batch_id='phase1c-revert-child'");
  const makeRevertToken = (revision: string, expected: number, approval: string) => {
    const hash = structuralHash({ operation: "REVERT", revision_id: revision, expected_revision: expected });
    const secret = randomBytes(32).toString("hex");
    pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability(${quote(approval)},${quote(hash)},ARRAY['REVERT'],now()+interval '5 minutes',${quote(secret)});`);
    return secret;
  };
  const blockedBrandRevert = makeRevertToken(brandRevision, 1, "phase1c-brand-revert");
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_revert_structural_revision(${quote(brandRevision)}::uuid,1,${quote(blockedBrandRevert)}); COMMIT;`, "STRUCTURAL_REVERT_ACTIVE_MODEL_DEPENDENT");
  const childRevert = makeRevertToken(childRevision, 1, "phase1c-child-revert");
  assert.equal(parseRpcResult(revertRpc(childRevision, 1, childRevert)).status, "REVERTED");
  assert.equal(parseRpcResult(revertRpc(brandRevision, 1, blockedBrandRevert)).status, "REVERTED");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_brands WHERE canonical_id='phase1c_revert_brand' AND deleted_at IS NOT NULL"), "1");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE canonical_id='phase1c_revert_brand.test_model' AND deleted_at IS NOT NULL"), "1");

  // Two independent SERIALIZABLE PostgreSQL sessions race to create the same
  // normalized model name. Exactly one may commit; hide its test row afterward.
  const raceIntent = (id: string): any => ({ operation: "CREATE_MODEL_BASIC", canonical_id: id, brand_id: "honda", name_en: "Phase1C Race Car",
    expected_revision: 0, identity_evidence: { granularity: "MODEL", model_name: "Phase1C Race Car", references: ["fixture:concurrent-race"] } });
  const raceOne = createRequest([raceIntent("honda.phase1c_race_one")], "phase1c-race-one").request;
  const raceTwo = createRequest([raceIntent("honda.phase1c_race_two")], "phase1c-race-two").request;
  const raceTokenOne = randomBytes(32).toString("hex"), raceTokenTwo = randomBytes(32).toString("hex");
  pgAsRpcActor(`SELECT vehicle_private.vm_issue_structural_capability('phase1c-race-one-cap',${quote(raceOne.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(raceTokenOne)});
      SELECT vehicle_private.vm_issue_structural_capability('phase1c-race-two-cap',${quote(raceTwo.batch_hash)},ARRAY['CREATE_MODEL_BASIC'],now()+interval '5 minutes',${quote(raceTokenTwo)});`);
  const raceResults = await Promise.all([rpcConcurrent(raceOne,raceTokenOne),rpcConcurrent(raceTwo,raceTokenTwo)]);
  const raceWinners = raceResults.filter(x => x.status===0);
  const raceLosers = raceResults.filter(x => x.status!==0);
  assert.equal(raceWinners.length,1,JSON.stringify(raceResults));
  assert.equal(raceLosers.length,1,JSON.stringify(raceResults));
  assert.match(raceLosers[0].output,/STRUCTURAL_NORMALIZED_IDENTITY_COLLISION|could not serialize access|serialization failure/i);
  const winningResult = parseRpcResult(raceWinners[0].output);
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE name_en='Phase1C Race Car' AND deleted_at IS NULL"),"1");
  const raceRevision = pg(`SELECT revision_id FROM vehicle_private.vm_structural_revisions WHERE batch_id=${quote(winningResult.batch_id)}`);
  const raceRevert = makeRevertToken(raceRevision,1,"phase1c-race-revert");
  assert.equal(parseRpcResult(revertRpc(raceRevision,1,raceRevert)).status,"REVERTED");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE name_en='Phase1C Race Car' AND deleted_at IS NULL"),"0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_serving_parity_check() WHERE NOT ok"),"0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_master_seed_check() WHERE NOT ok"),"0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_engine_rules_check()"),"0");

  const forged = { ...(request as any), actor_kind: "ADMIN" };
  const { payload_hash: _payloadHash, ...forgedWithoutHash } = forged;
  forged.payload_hash = structuralHash(forgedWithoutHash);
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(forged))}::jsonb,'${token}'); COMMIT;`,
    "INVALID_STRUCTURAL_RPC_ENVELOPE");
  expectLoginRoleFailure(rpcUser,`BEGIN ISOLATION LEVEL READ COMMITTED; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(request))}::jsonb,'${token}'); COMMIT;`,
    "STRUCTURAL_RPC_REQUIRES_SERIALIZABLE");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE canonical_id='honda.forbidden'"), "0");

  const raptorIntent = (inputById.get(held[0].canonical_id) as any).create_intent;
  const raptorBatch: Batch = { batch_id: "raptor-hold-check", reason: "frozen Raptor hold regression", source_ref: "frozen-preflight:2026-10-13", observed_at: "2026-10-13T00:00:00.000Z", intents: [raptorIntent] };
  const raptorPlan = planStructuralChanges(snapshot, raptorBatch);
  assert.equal(raptorPlan.changes.length, 0);
  assert.match(raptorPlan.holds[0].detail, /REGISTRATION_CLASS_PARENT_ALIAS_CONFLICT:ford\.ranger_double_cab/);
  const report = {
    schema: "tdr.phase1c.real-postgresql-acceptance.v1",
    executed_at_utc: new Date().toISOString(),
    exact_command: "node --experimental-strip-types scripts/phase1c-postgres-acceptance.ts",
    docker_image: image,
    database: `PostgreSQL ${dbVersion}, Docker network=none, tmpfs-only, no published port`,
    replayed_repository_schema: "v12,v15,v22,v48,v57-v64",
    catalog_baseline_and_post_apply: "parity, seed and engine checks passed",
    valid_identities: validated.length, registrations: 47109, basic_models_created: 8,
    raw_ice_evidence_groups: Object.keys(rawIceEvidence).length,
    auxiliary_create_test_rows: "two models and one brand were created for revert/concurrency cases, then soft-hidden",
    current_catalog_models: 1, basic_market_analysis_identities: 8,
    ford_ranger_raptor: "HOLD: REGISTRATION_CLASS_PARENT_ALIAS_CONFLICT:ford.ranger_double_cab",
    frozen_owner_decisions: 244, owner_ledger_sha256: frozenLedgerHash, identity_snapshot_sha256: frozenSnapshotHash,
    receipt_replay: "same receipt; changed payload under the same idempotency key rejected",
    collision_checks: "duplicate canonical ID and frozen-snapshot-normalized alias collisions rejected",
    production_or_staging_connections: 0,
    access_controls: "structural RPC applied through non-superuser phase1c_rpc_actor login with approver role; unprivileged authenticated direct DML denied; service_role EXECUTE denied; forged actor envelope denied; READ COMMITTED denied; expired capability rejected; injected mid-batch error rolled back",
    alias_updates: "fresh alias revision 1 -> 2 succeeds; stale revision rejected; compensating revert restores aliases at revision 3 and retries idempotently",
    create_reverts: "soft-hide requires current revisions and no active model dependents; brand revert held until child identity is hidden",
    concurrent_creates: "two real PostgreSQL SERIALIZABLE sessions raced on one normalized name; exactly one committed, then was soft-hidden",
    frozen_owner_ledger_sha256: frozenLedgerHash,
    frozen_snapshot_sha256: frozenSnapshotHash,
    migration_replay: files,
  };
  const evidenceDir = path.join(root, "docs/vehicle-db/drafts/phase1c");
  fs.writeFileSync(path.join(evidenceDir, "postgres_acceptance_report.json"), `${JSON.stringify(report,null,2)}\n`);
  console.log(JSON.stringify(report, null, 2));
} finally {
  run("docker", ["rm", "--force", name], undefined, true);
}
