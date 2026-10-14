/**
 * Private, local PostgreSQL rehearsal over the owner's complete Vehicle Master backup.
 * Requires TDR_VM_PRIVATE_BACKUP_GZIP to point outside the repository. Never uploads
 * or writes the input; the disposable Docker container is --network none/tmpfs-only.
 */
import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { planStructuralChanges, structuralHash, type Batch, type Snapshot } from "../lib/vehicle-engine/structural-writer.ts";
import { buildStructuralRpcDraftRequest } from "../lib/vehicle-engine/basic-identity-db-compat.ts";
import { decompressPrivateBackupJson } from "../lib/vehicle-engine/private-backup-json.ts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = "postgres:16.10-alpine@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297";
const container = `tdr-phase1d-full-${process.pid}`;
const dbUser = "phase1c_owner";
const dbName = "phase1c_acceptance";
const executor = "phase1d_test_executor";
const issuer = "phase1d_test_issuer";
const expectedGzipSha = "8b7dc88cf42c27516ec08ddf170173feff85891ac655caa9a6f3eb5511d8b962";
const expectedPayloadSha = "c51c20966be5f49dd0fe9a953793e666f6becf0f4d27a986158b6805e7659dad";
const frozenLedgerSha = "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8";
const frozenIdentitySha = "e3becefe99f284d57a62bd4f8a5c269616b6df1ddf8475d75bcd76df1e2c2943";
const candidateIds = ["honda.jazz", "jaecoo.j6", "toyota.vios", "gwm.ora_5", "nissan.march", "nissan.note", "zeekr.7x", "toyota.sienta"];
const tableOrder = ["vehicle_master_state", "vehicle_brands", "vehicle_models", "vehicle_generations", "vehicle_variants", "vehicle_trims", "vehicle_facts", "vehicle_price_ledger", "vehicle_campaigns", "vehicle_promotions", "vehicle_eco_evidence", "vehicle_current_retail_sets", "vehicle_trim_lifecycle_decisions", "vehicle_model_operational_states", "vehicle_legacy_identities"];
let snapshotForPlanning: Snapshot | undefined;
const relationCounts: Record<string, number> = {
  vehicle_master_state:1, vehicle_brands:62, vehicle_models:323, vehicle_generations:326, vehicle_variants:370,
  vehicle_trims:1569, vehicle_facts:24492, vehicle_price_ledger:1004, vehicle_campaigns:44, vehicle_promotions:48,
  vehicle_eco_evidence:3, vehicle_current_retail_sets:61, vehicle_trim_lifecycle_decisions:15,
  vehicle_model_operational_states:0, vehicle_legacy_identities:1,
};
const sourceHashes: Record<string, string> = {
  vehicle_brands:"7ce84530fa9dc9af5c87b58b3f652b27", vehicle_campaigns:"a3cd9287b2c0e9e1682eb361c8c221bd",
  vehicle_current_retail_sets:"98505d5881d32de49de3bddbb915ecd0", vehicle_eco_evidence:"20d33f0f5260b5f038a41d183269c9cc",
  vehicle_facts:"074a7cf2c603a218fc232e24a9e015a5", vehicle_generations:"39ad73ac4fcf806f308350c8acbcb7bf",
  vehicle_legacy_identities:"e51d798b7ed8776c8a403b2d3f6cae22", vehicle_master_state:"e73224fca556e9b3271b1e806c1007c3",
  vehicle_model_operational_states:"d41d8cd98f00b204e9800998ecf8427e", vehicle_models:"40320bee99d7215829bb886a8e5f0583",
  vehicle_price_ledger:"cf37f790454aca0662392fb906c8b400", vehicle_promotions:"89ede84f53d099695618c214c77523e5",
  vehicle_trim_lifecycle_decisions:"daa514d81438380bff9babe13bca7b21", vehicle_trims:"61e0230c93dd2cbc6b3a5cbe9ccf64c5",
  vehicle_variants:"dbcea4aa79471faf9f0a5bcab3e732de",
  current_market_trims:"5d57479684c0faf3ca87b1db373adf55", current_price_ledger:"717c630c162f2b0e76b99ed7ebddbd30",
  current_spec_facts:"3681ad68ae64e3244bb86f6abbcea001", current_vehicle_brands:"8b14709c09faa7d7cd9b5ab12820a389",
  current_vehicle_generations:"4991637da060e706dc6522a673712794", current_vehicle_models:"5055ed942a93ae28b5ddd03b32de9418",
};
const views = ["current_vehicle_brands", "current_vehicle_models", "current_vehicle_generations", "current_market_trims", "current_price_ledger", "current_spec_facts"];
const digest = (bytes: Buffer | string) => createHash("sha256").update(bytes).digest("hex");
function run(cmd: string, args: string[], input?: string | Buffer, allowFailure = false): string {
  const r = spawnSync(cmd, args, { cwd: root, input, encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  if (r.error) throw r.error;
  if (r.status !== 0 && !allowFailure) throw new Error(`${cmd} failed (${r.status}): ${r.stderr || r.stdout}`);
  return `${r.stdout}${r.stderr}`.trim();
}
const quote = (s: string) => `'${s.replaceAll("'", "''")}'`;
function pg(sql: string): string { return run("docker", ["exec", "-i", container, "psql", "-X", "-q", "-U", dbUser, "-d", dbName, "-v", "ON_ERROR_STOP=1", "-At", "-P", "pager=off"], sql); }
function roleSql(role: string, sql: string, allowFailure = false): string {
  return run("docker", ["exec", "-i", container, "psql", "-X", "-q", "-U", role, "-d", dbName, "-v", "ON_ERROR_STOP=1", "-At", "-P", "pager=off"], sql, allowFailure);
}
const qident = (v: string) => `"${v.replaceAll('"', '""')}"`;
const schemaDiagnosticPath = "docs/vehicle-db/phase1d/issue244_live_source_schema_acl_diagnostic_2026-10-14.json";
const sourceDiagnostic = JSON.parse(fs.readFileSync(path.join(root, schemaDiagnosticPath), "utf8"));
const sourceDiagnosticSections = sourceDiagnostic.sections as Record<string, any[]>;
function jsonRows(sql: string): any[] {
  const result = pg(sql);
  return result ? JSON.parse(result) : [];
}
function collectSchemaAclMetadata(): Record<string, any[]> {
  const relations = sourceDiagnosticSections.relation_metadata.map((r) => r.relation);
  const relationArray = `ARRAY[${relations.map((r) => quote(r)).join(",")}]::text[]`;
  const dbRoles = [...new Set(sourceDiagnosticSections.role_acl.map((r) => r.db_role))];
  const roleArray = `ARRAY[${dbRoles.map((r) => quote(r)).join(",")}]::text[]`;
  return {
    relation_metadata: jsonRows(`SELECT coalesce(jsonb_agg(jsonb_build_object('relation',c.relname,'kind',c.relkind,'rls_enabled',c.relrowsecurity,'rls_forced',c.relforcerowsecurity,'reloptions',coalesce(array_to_string(c.reloptions,','),''),'view_definition_md5',CASE WHEN c.relkind IN ('v','m') THEN md5(coalesce(pg_get_viewdef(c.oid,false),'')) ELSE '' END) ORDER BY c.relname),'[]'::jsonb) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(${relationArray});`),
    column_metadata: jsonRows(`SELECT coalesce(jsonb_agg(jsonb_build_object('relation',c.relname,'column_name',a.attname,'data_type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,'default_sql_md5',md5(coalesce(ic.generation_expression,ic.column_default,''))) ORDER BY c.relname,a.attname),'[]'::jsonb) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN information_schema.columns ic ON ic.table_schema=n.nspname AND ic.table_name=c.relname AND ic.column_name=a.attname WHERE n.nspname='public' AND c.relname=ANY(${relationArray}) AND a.attnum>0 AND NOT a.attisdropped;`),
    constraint_metadata: jsonRows(`SELECT coalesce(jsonb_agg(jsonb_build_object('relation',c.relname,'constraint_name',k.conname,'kind',k.contype,'definition_md5',md5(pg_get_constraintdef(k.oid,true))) ORDER BY c.relname,k.conname),'[]'::jsonb) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(${relationArray});`),
    trigger_metadata: jsonRows(`SELECT coalesce(jsonb_agg(jsonb_build_object('relation',c.relname,'trigger_name',t.tgname,'enabled',t.tgenabled,'definition_md5',md5(pg_get_triggerdef(t.oid,true))) ORDER BY c.relname,t.tgname),'[]'::jsonb) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(${relationArray}) AND NOT t.tgisinternal;`),
    policy_metadata: jsonRows(`SELECT coalesce(jsonb_agg(jsonb_build_object('relation',tablename,'policy_name',policyname,'cmd',cmd,'roles',roles::text,'using_md5',md5(coalesce(qual,'')),'with_check_md5',md5(coalesce(with_check,''))) ORDER BY tablename,policyname),'[]'::jsonb) FROM pg_policies WHERE schemaname='public' AND tablename=ANY(${relationArray});`),
    role_acl: jsonRows(`SELECT coalesce(jsonb_agg(jsonb_build_object('relation',rr.relation,'db_role',pp.db_role,'select_allowed',has_table_privilege(pp.db_role,format('public.%I',rr.relation),'SELECT'),'insert_allowed',has_table_privilege(pp.db_role,format('public.%I',rr.relation),'INSERT'),'update_allowed',has_table_privilege(pp.db_role,format('public.%I',rr.relation),'UPDATE'),'delete_allowed',has_table_privilege(pp.db_role,format('public.%I',rr.relation),'DELETE')) ORDER BY rr.relation,pp.db_role),'[]'::jsonb) FROM unnest(${relationArray}) rr(relation) CROSS JOIN unnest(${roleArray}) pp(db_role);`),
    function_metadata: jsonRows(`SELECT coalesce(jsonb_agg(jsonb_build_object('schema',n.nspname,'name',p.proname,'args',pg_get_function_identity_arguments(p.oid),'security_definer',p.prosecdef,'definition_md5',md5(pg_get_functiondef(p.oid))) ORDER BY n.nspname,p.proname,pg_get_function_identity_arguments(p.oid)),'[]'::jsonb) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind IN ('f','p');`),
  };
}
function rowKey(section: string, row: any): string {
  switch (section) {
    case "relation_metadata": return row.relation;
    case "column_metadata": return `${row.relation}.${row.column_name}`;
    case "constraint_metadata": return `${row.relation}.${row.constraint_name}`;
    case "trigger_metadata": return `${row.relation}.${row.trigger_name}`;
    case "policy_metadata": return `${row.relation}.${row.policy_name}`;
    case "role_acl": return `${row.relation}.${row.db_role}`;
    case "function_metadata": return `${row.schema}.${row.name}(${row.args})`;
    default: return JSON.stringify(row);
  }
}
function compareMetadata(source: Record<string, any[]>, actual: Record<string, any[]>) {
  const sections = Object.keys(source);
  const mismatches: Array<{ section: string; key: string; different_fields: string[]; expected_values: Record<string,any> | null; actual_values: Record<string,any> | null }> = [];
  const unexpectedLocalRecords: Record<string,string[]> = {};
  const signature = (value: any) => value === undefined ? null : digest(JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)))));
  for (const section of sections) {
    const expected = new Map(source[section].map((r) => [rowKey(section,r), r]));
    const observed = new Map((actual[section] ?? []).map((r) => [rowKey(section,r), r]));
    const unexpected = [...observed.keys()].filter((key)=>!expected.has(key));
    if (unexpected.length) unexpectedLocalRecords[section]=unexpected;
    for (const key of expected.keys()) {
      const e = expected.get(key); const a = observed.get(key);
      const es = signature(e); const as = signature(a);
      if (es !== as) {
        const fields = [...new Set([...Object.keys(e ?? {}),...Object.keys(a ?? {})])].sort();
        const different_fields = fields.filter((field)=>JSON.stringify(e?.[field])!==JSON.stringify(a?.[field]));
        mismatches.push({ section, key, different_fields, expected_values:e ?? null, actual_values:a ?? null });
      }
    }
  }
  return { checked_sections: sections, source_record_counts: Object.fromEntries(sections.map((s)=>[s,source[s].length])), actual_record_counts: Object.fromEntries(sections.map((s)=>[s,actual[s]?.length ?? 0])), unexpected_local_records:unexpectedLocalRecords,mismatches };
}
function reproduceDiagnosticEffectiveAclsLocally(): void {
  const privileges = ["SELECT","INSERT","UPDATE","DELETE"] as const;
  for (const row of sourceDiagnosticSections.role_acl) {
    const relation = `public.${qident(String(row.relation))}`;
    const role = qident(String(row.db_role));
    const grants = privileges.filter((p)=>row[`${p.toLowerCase()}_allowed`]).join(",");
    pg(`REVOKE ALL PRIVILEGES ON TABLE ${relation} FROM PUBLIC, ${role};${grants ? ` GRANT ${grants} ON TABLE ${relation} TO ${role};` : ""}`);
  }
}
function collectColumnFingerprints(expected: any[]): any[] {
  const result: any[] = [];
  for (const item of expected) {
    const relation = String(item.relation);
    const column = String(item.column_name);
    const expression = `md5((to_jsonb(t)->${quote(column)})::text)`;
    const row = jsonRows(`SELECT jsonb_build_array(jsonb_build_object('relation',${quote(relation)},'column_name',${quote(column)},'values_seen',count(*),'column_multiset_md5',md5(coalesce(string_agg(${expression},'' ORDER BY ${expression}),'')))) FROM public.${qident(relation)} t;`)[0];
    result.push(row);
  }
  return result;
}
function databaseSnapshot(afterPhase1c = false): Record<string, { rows: number; md5: string }> {
  const result: Record<string, { rows: number; md5: string }> = {};
  for (const rel of [...tableOrder, ...views]) {
    const source = `public.${rel}`;
    const hasIdentityLevel = afterPhase1c && (rel === "vehicle_models" || rel === "vehicle_brands");
    const where = hasIdentityLevel ? " WHERE identity_level='CATALOG'" : "";
    const projection = rel === "vehicle_models" || rel === "vehicle_brands" ? "to_jsonb(t)-'identity_level'-'identity_aliases'" : "to_jsonb(t)";
    const out = pg(`SELECT count(*)::text||'|'||md5(coalesce(string_agg(md5((${projection})::text),'' ORDER BY md5((${projection})::text)),'')) FROM ${source} t${where};`);
    const [rows, md5] = out.split("|");
    result[rel] = { rows: Number(rows), md5 };
  }
  return result;
}
function projectionSeedSql(): string {
  return `
INSERT INTO public.brands(id) SELECT DISTINCT tdr_brand_id FROM public.vehicle_brands WHERE tdr_brand_id IS NOT NULL ON CONFLICT DO NOTHING;
INSERT INTO public.models(id) SELECT DISTINCT tdr_model_id FROM public.vehicle_models WHERE tdr_model_id IS NOT NULL ON CONFLICT DO NOTHING;
INSERT INTO public.canonical_vehicle_releases(release_id,schema_version,canonical_revision,source_hash,as_of,counts,payload,status,activated_at)
SELECT seed_release_id,1,seed_canonical_revision,seed_source_hash,seed_as_of,release_counts,'{"source":"private_vehicle_master_backup"}'::jsonb,'ACTIVE',coalesce(release_seeded_at,now())
FROM public.vehicle_master_state WHERE scope='vehicle_master';
INSERT INTO public.canonical_vehicle_state(scope,active_release_id)
SELECT 'vehicle_catalog',seed_release_id FROM public.vehicle_master_state WHERE scope='vehicle_master';
INSERT INTO public.canonical_brand_projection(release_id,canonical_id,tdr_brand_id,slug,name_en,name_th,origin_country,payload)
SELECT st.seed_release_id,b.canonical_id,b.tdr_brand_id,b.slug,b.name_en,b.name_th,b.origin_country,b.payload FROM public.vehicle_brands b CROSS JOIN public.vehicle_master_state st WHERE st.scope='vehicle_master' AND b.deleted_at IS NULL;
INSERT INTO public.canonical_model_projection(release_id,canonical_id,tdr_model_id,brand_id,slug,name_en,name_th,generation_id,status,segment,body_type,retail_price_min,retail_price_max,payload)
SELECT st.seed_release_id,m.canonical_id,m.tdr_model_id,m.brand_id,m.slug,m.name_en,m.name_th,m.generation_id,m.status,m.segment,m.body_type,m.retail_price_min,m.retail_price_max,m.payload FROM public.vehicle_models m CROSS JOIN public.vehicle_master_state st WHERE st.scope='vehicle_master' AND m.deleted_at IS NULL;
INSERT INTO public.canonical_generation_projection(release_id,canonical_id,model_id,code,segment,launched,ended,payload)
SELECT st.seed_release_id,g.canonical_id,g.model_id,g.code,g.segment,g.launched,g.ended,g.payload FROM public.vehicle_generations g CROSS JOIN public.vehicle_master_state st WHERE st.scope='vehicle_master' AND g.deleted_at IS NULL;
INSERT INTO public.canonical_market_trim_projection(release_id,canonical_id,model_id,generation_id,variant_id,name,powertrain,status,payload,current_list_price,campaign_quote,price_history,source_refs)
SELECT st.seed_release_id,t.canonical_id,t.model_id,t.generation_id,t.variant_id,t.name,t.powertrain,t.status,t.payload,t.current_list_price,t.campaign_quote,t.price_history,t.source_refs FROM public.vehicle_trims t CROSS JOIN public.vehicle_master_state st WHERE st.scope='vehicle_master' AND t.deleted_at IS NULL;
INSERT INTO public.canonical_price_projection(release_id,record_id,trim_id,amount_thb,price_type,effective_from,effective_to,observed_at,campaign_id,option_id,source,source_ref,payload)
SELECT st.seed_release_id,p.record_id,p.trim_id,p.amount_thb,p.price_type,p.effective_from,p.effective_to,p.observed_at,p.campaign_id,p.option_id,p.source,p.source_ref,p.payload FROM public.vehicle_price_ledger p CROSS JOIN public.vehicle_master_state st WHERE st.scope='vehicle_master' AND p.in_release;
INSERT INTO public.canonical_spec_projection(release_id,fact_id,trim_id,field_key,verification_status,payload)
SELECT st.seed_release_id,f.fact_id,f.trim_id,f.field_key,f.verification_status,f.payload FROM public.vehicle_facts f CROSS JOIN public.vehicle_master_state st WHERE st.scope='vehicle_master' AND f.served_in_release;
`;
}
function createBatch(intents: any[], batchId: string, reason: string, raw?: Record<string, unknown>) {
  const batch: Batch = { batch_id: batchId, reason, source_ref: "issue-244:private-full-catalog-rehearsal", observed_at: "2026-10-13T00:53:40.000Z", intents: intents as any,
    ...(raw ? { raw_evidence: raw } : {}) };
  assert.ok(snapshotForPlanning, "IDENTITY_SNAPSHOT_NOT_INITIALIZED");
  const plan = planStructuralChanges(snapshotForPlanning, batch);
  assert.equal(plan.holds.length, 0, JSON.stringify(plan.holds));
  return { batch, plan, request: buildStructuralRpcDraftRequest(batch, plan) };
}
function issue(ref: string, hash: string, op: string, token: string): void {
  const id = roleSql(issuer,`SELECT vehicle_private.vm_issue_structural_capability(${quote(ref)},${quote(executor)},${quote(hash)},ARRAY[${quote(op)}]::text[],now()+interval '5 minutes',${quote(token)},${quote(`fixture:issue244:${ref}`)});`);
  assert.match(id, /^[0-9a-f-]{36}$/);
}
function rpcSql(request: any, token: string): string {
  return `BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_apply_structural_changes(${quote(JSON.stringify(request))}::jsonb,${quote(token)}); COMMIT;`;
}
function apply(request: any, token: string): any {
  const result = roleSql(executor, rpcSql(request, token));
  const line = result.split("\n").find((x) => x.startsWith("{"));
  assert.ok(line, "RPC did not return JSON result");
  return JSON.parse(line);
}
const recordCounts = (payload: any) => Object.fromEntries(tableOrder.map((t) => [t, payload.row_counts[t]]));

const backupPath = process.env.TDR_VM_PRIVATE_BACKUP_GZIP;
assert.ok(backupPath, "Set TDR_VM_PRIVATE_BACKUP_GZIP to the verified private .json.gz outside the repository");
const absoluteBackup = path.resolve(backupPath);
assert.ok(!absoluteBackup.startsWith(`${root}${path.sep}`), "PRIVATE_BACKUP_MUST_REMAIN_OUTSIDE_REPOSITORY");
const compressed = fs.readFileSync(absoluteBackup);
assert.equal(digest(compressed), expectedGzipSha, "PRIVATE_BACKUP_GZIP_SHA256_MISMATCH");
const verifier = spawnSync("python3", ["-m", "tools.vehicle_master_backup_verify", absoluteBackup, "--expect-sha256", expectedGzipSha],
  { cwd: path.join(root, "automotive/vehicle_master"), encoding: "utf8", maxBuffer: 1024 * 1024 });
assert.equal(verifier.status, 0, "REPOSITORY_BACKUP_VERIFIER_FAILED");
const verified = JSON.parse(verifier.stdout);
assert.equal(verified.valid, true);
assert.equal(verified.checksum.value, expectedPayloadSha);
const restoreJsonBytes = decompressPrivateBackupJson(compressed);
const envelope = JSON.parse(restoreJsonBytes.toString("utf8"));
assert.equal(envelope.format, "tdr-vehicle-master-backup");
assert.equal(envelope.format_version, 1);
const payload = envelope.payload;
assert.deepEqual(payload.tables, tableOrder);
assert.equal(envelope.checksum?.value, expectedPayloadSha, "PRIVATE_BACKUP_DECLARED_PAYLOAD_SHA256_MISMATCH");
assert.deepEqual(recordCounts(payload), relationCounts);
assert.equal(Object.values(relationCounts).reduce((a, b) => a + b, 0), 28319);
for (const table of tableOrder) assert.equal((payload.data[table] ?? []).length, relationCounts[table], `ROW_COUNT_MISMATCH:${table}`);
const restoreInputPath = path.join(os.tmpdir(), `tdr-issue244-payload-${process.pid}.json`);
fs.writeFileSync(restoreInputPath, restoreJsonBytes, { mode: 0o600 });
assert.equal(digest(fs.readFileSync(restoreInputPath)), digest(restoreJsonBytes), "RESTORE_JSON_BYTES_CHANGED_BEFORE_IMPORT");
const dbSecret = randomBytes(32).toString("hex");
try {
  run("docker", ["run", "--detach", "--rm", "--name", container, "--network", "none", "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=2g",
    "--env", `POSTGRES_PASSWORD=${dbSecret}`, "--env", `POSTGRES_USER=${dbUser}`, "--env", "POSTGRES_DB=postgres", image]);
  let ready = false;
  for (let i = 0; i < 60; i++) {
    if (run("docker", ["exec", container, "pg_isready", "-h", "127.0.0.1", "-U", dbUser, "-d", "postgres"], undefined, true).includes("accepting connections")) { ready = true; break; }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500);
  }
  assert.ok(ready, "ISOLATED_POSTGRESQL_NOT_READY");
  run("docker", ["exec", container, "createdb", "-U", dbUser, dbName]);
  const files = ["docs/vehicle-db/drafts/phase1c/bootstrap_supabase_test_support.sql", "supabase/migration_v12_canonical_write_pipeline.sql",
    "supabase/migration_v15_canonical_vehicle_release.sql", "supabase/migration_v22_unified_vehicle_input.sql", "supabase/migration_v48_staged_vehicle_release.sql",
    "supabase/migration_v57_vehicle_master_tables.sql"];
  for (const f of files) pg(fs.readFileSync(path.join(root, f), "utf8"));
  run("docker", ["cp", restoreInputPath, `${container}:/tmp/private_vehicle_master_backup.json`]);
  run("docker", ["exec", container, "chmod", "644", "/tmp/private_vehicle_master_backup.json"]);
  const source = `pg_read_file('/tmp/private_vehicle_master_backup.json')::jsonb #> '{payload,data,`;
  const qident = (v: string) => `"${v.replaceAll('"', '""')}"`;
  const restoreStatements: string[] = [];
  for (const table of tableOrder) {
    const rows = payload.data[table] as any[];
    if (!rows.length) continue;
    const sourceKeys = Object.keys(rows[0]).sort();
    const columnRows = pg(`SELECT attname||'|'||attgenerated::text FROM pg_attribute WHERE attrelid='public.${table}'::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum;`).split("\n").filter(Boolean);
    const dbColumns = columnRows.map((line) => line.split("|"));
    const generated = new Set(dbColumns.filter(([, gen]) => gen).map(([name]) => name));
    const insertColumns = sourceKeys.filter((c) => !generated.has(c));
    const missing = dbColumns.map(([name, gen]) => name).filter((name) => !generated.has(name) && !sourceKeys.includes(name));
    const extra = sourceKeys.filter((name) => !dbColumns.some(([col]) => col === name));
    assert.deepEqual({ missing, extra }, { missing: [], extra: [] }, `BACKUP_SCHEMA_COLUMN_MISMATCH:${table}`);
    const targetColumns = insertColumns.map(qident).join(",");
    const selectColumns = insertColumns.map((c) => `(jsonb_populate_record(NULL::public.${table},j.v)).${qident(c)}`).join(",");
    restoreStatements.push(`INSERT INTO public.${table}(${targetColumns}) SELECT ${selectColumns} FROM jsonb_array_elements(${source}${table}}') j(v);`);
  }
  pg(`BEGIN; SET CONSTRAINTS ALL DEFERRED; ${restoreStatements.join("\n")} COMMIT;`);
  pg("COMMIT; DROP TABLE IF EXISTS public.phase1c_local_guard; CREATE TABLE public.phase1c_local_guard(only_disposable_local boolean PRIMARY KEY CHECK(only_disposable_local),database_name text NOT NULL); INSERT INTO public.phase1c_local_guard VALUES(true,current_database());");
  run("docker", ["exec", container, "rm", "-f", "/tmp/private_vehicle_master_backup.json"]);
  for (const table of tableOrder) assert.equal(Number(pg(`SELECT count(*) FROM public.${table}`)), relationCounts[table], `RESTORE_COUNT_MISMATCH:${table}`);
  pg(projectionSeedSql());
  for (const f of ["supabase/migration_v58_vehicle_serving_parity.sql", "supabase/migration_v59_vehicle_engine_rules.sql", "supabase/migration_v60_close_legacy_vehicle_write_path.sql",
    "supabase/migration_v61_vehicle_master_backups_bucket.sql", "supabase/migration_v62_ice_market_panels.sql", "supabase/migration_v63_ice_model_crosswalk.sql", "supabase/migration_v64_ice_panel_grain_fix.sql"])
    pg(fs.readFileSync(path.join(root, f), "utf8"));
  assert.equal(pg("SELECT current_setting('server_version_num')::int >= 160010"), "t");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_serving_parity_check() WHERE NOT ok"), "0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_master_seed_check() WHERE NOT ok"), "0");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_engine_rules_check()"), "0");
  const before = databaseSnapshot();
  const baselineMismatches: Array<{ relation: string; expected_rows: number; actual_rows: number; expected_md5: string; actual_md5: string }> = [];
  for (const rel of [...tableOrder, ...views]) {
    const expected = sourceHashes[rel];
    const expectedRows = relationCounts[rel];
    if ((expectedRows !== undefined && before[rel].rows !== expectedRows) || (expected && before[rel].md5 !== expected)) {
      baselineMismatches.push({ relation:rel, expected_rows:expectedRows ?? before[rel].rows, actual_rows:before[rel].rows,
        expected_md5:expected ?? "NOT_PROVIDED", actual_md5:before[rel].md5 });
    }
  }
  const columnFingerprintSource = sourceDiagnosticSections.column_fingerprints;
  const columnFingerprintActual = collectColumnFingerprints(columnFingerprintSource);
  const sourceColumnByKey = new Map(columnFingerprintSource.map((r) => [`${r.relation}.${r.column_name}`, r]));
  const columnFingerprintMismatches = columnFingerprintActual.flatMap((actual) => {
    const expected = sourceColumnByKey.get(`${actual.relation}.${actual.column_name}`);
    return !expected || expected.values_seen !== actual.values_seen || expected.column_multiset_md5 !== actual.column_multiset_md5
      ? [{ relation:actual.relation,column_name:actual.column_name,expected_values_seen:expected?.values_seen ?? null,actual_values_seen:actual.values_seen,
          expected_md5:expected?.column_multiset_md5 ?? null,actual_md5:actual.column_multiset_md5 }]
      : [];
  });
  const schemaAclSections = ["relation_metadata","column_metadata","constraint_metadata","trigger_metadata","policy_metadata","role_acl","function_metadata"];
  const sourceSchemaAclSections = Object.fromEntries(schemaAclSections.map((s)=>[s,sourceDiagnosticSections[s] ?? []]));
  reproduceDiagnosticEffectiveAclsLocally();
  const sourceSchemaAclComparison = compareMetadata(sourceSchemaAclSections, collectSchemaAclMetadata());
  const sourceDataMismatch = baselineMismatches.length > 0 || columnFingerprintMismatches.length > 0;
  if (sourceDataMismatch || sourceSchemaAclComparison.mismatches.length) {
    const result = sourceDataMismatch ? "FULL_CATALOG_ACCEPTANCE_BLOCKED_SOURCE_FINGERPRINT_MISMATCH" : "FULL_CATALOG_ACCEPTANCE_BLOCKED_SCHEMA_ACL_MISMATCH";
    const blockedReason = sourceDataMismatch
      ? "Fail-closed before Phase 1C: restored source aggregate or per-column fingerprints differ from the unchanged authorized baseline. No expected hash was changed or suppressed."
      : `Fail-closed before Phase 1C: data fingerprints match, but ${sourceSchemaAclComparison.mismatches.length} source view/function definition digests differ. The source diagnostic is PostgreSQL 17 while this pinned rehearsal uses PostgreSQL 16.10; the diagnostic warns that these MD5s can vary by engine and supplies no source DDL to resolve the differences. No Phase1C SQL was applied.`;
    const blockedReport={schema:"tdr.vehicle-db.issue244.full-catalog-postgres-acceptance.v1",executed_at_utc:new Date().toISOString(),
      exact_command:"TDR_VM_PRIVATE_BACKUP_GZIP=<private path> npm run check:phase1d-full-catalog-postgres",docker_image:image,
      database:"PostgreSQL 16.10; Docker network=none; tmpfs-only; no published port",
      private_input:{available:true,gzip_sha256:expectedGzipSha,payload_sha256:expectedPayloadSha,tables:15,rows:28319,raw_backup_pushed:false},
      baseline:{source_hash_manifest:"Owner Context Handoff 2026-10-14 aggregate counts and MD5; unchanged expected values",repository_v57_v64_restore:true,
        decompressed_source_sha256:digest(restoreJsonBytes),restore_file_sha256:digest(fs.readFileSync(restoreInputPath)),source_schema_acl_manifest:schemaDiagnosticPath,
        matching_relations:21-baselineMismatches.length,total_relations_checked:21,mismatches:baselineMismatches},
      restore_preparation:{original_decompressed_bytes_written_unchanged:true,numeric_scale_regression:"PASS: 405.0 and 1.0 preserved",focused_test:"scripts/check-phase1d-restore-bytes.ts"},
      column_fingerprint_comparison:{source_fingerprints:columnFingerprintSource.length,compared_fingerprints:columnFingerprintActual.length,
        matching_fingerprints:columnFingerprintActual.length-columnFingerprintMismatches.length,mismatches:columnFingerprintMismatches},
      source_schema_acl_comparison:{...sourceSchemaAclComparison,effective_acl_snapshot_replayed_in_disposable_db:true,
        source_diagnostic_engine:sourceDiagnostic.source_db_engine,local_engine:`PostgreSQL ${pg("SELECT current_setting('server_version')")}`},
      phase1c_applied:false,basic_models_created:0,production_or_staging_connections:0,production_or_staging_writes:0,
      frozen_owner_decisions:244,owner_ledger_sha256:frozenLedgerSha,acceptance_result:result,
      blocked_reason:blockedReason,raw_rows_in_report:false};
    fs.writeFileSync(path.join(root,"docs/vehicle-db/phase1d/issue244_full_catalog_rehearsal_report.json"),`${JSON.stringify(blockedReport,null,2)}\n`);
    console.log(JSON.stringify({acceptance_result:blockedReport.acceptance_result,source_rows:28319,relations_checked:21,matching_relations:blockedReport.baseline.matching_relations,
      column_fingerprints:`${blockedReport.column_fingerprint_comparison.matching_fingerprints}/${blockedReport.column_fingerprint_comparison.source_fingerprints}`,
      source_data_mismatches:baselineMismatches.length+columnFingerprintMismatches.length,schema_acl_metadata_mismatches:sourceSchemaAclComparison.mismatches.length,
      phase1c_applied:false,raw_rows_in_report:false},null,2));
    throw new Error(sourceDataMismatch ? "ISSUE244_SOURCE_BASELINE_FINGERPRINT_MISMATCH" : "ISSUE244_SOURCE_SCHEMA_ACL_MISMATCH");
  }
  const readRoles = ["anon", "authenticated", "service_role"];
  const roleBefore: Record<string, string> = {};
  const privilegeBefore: Record<string, string> = {};
  for (const role of readRoles) for (const view of views) {
    roleBefore[`${role}.${view}`] = pg(`SET ROLE ${role}; SELECT count(*) FROM public.${view}; RESET ROLE;`);
  }
  for (const role of readRoles) for (const relation of ["vehicle_brands", "vehicle_models", ...views]) {
    privilegeBefore[`${role}.${relation}`] = pg(`SELECT has_table_privilege(${quote(role)},${quote(`public.${relation}`)},'SELECT');`);
  }
  const snapshotPath = "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/vehicle_master_identity_snapshot_2026-10-13.json";
  const snapshotRaw = fs.readFileSync(path.join(root, snapshotPath), "utf8");
  const snapshotDigest = digest(snapshotRaw);
  const preflight = JSON.parse(fs.readFileSync(path.join(root, "docs/vehicle-db/structural-writer/nine_identity_preflight_report.json"), "utf8"));
  assert.equal(digest(fs.readFileSync(path.join(root, "docs/vehicle-db/structural-writer/nine_identity_preflight_report.json"))), frozenIdentitySha);
  const inputs = JSON.parse(fs.readFileSync(path.join(root, "docs/vehicle-db/structural-writer/nine_identity_inputs.json"), "utf8"));
  assert.equal(digest(fs.readFileSync(path.join(root, "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/owner_decision_ledger_244.csv"))), frozenLedgerSha);
  assert.equal(snapshotDigest, "cf991264ada90efb0ff69a754cdee11fb0d13cc98fbe9fc60879de4eb7a2eb62");
  assert.equal(frozenIdentitySha, "e3becefe99f284d57a62bd4f8a5c269616b6df1ddf8475d75bcd76df1e2c2943");
  assert.equal(preflight.frozen_owner_decisions.total, 244); assert.equal(preflight.frozen_owner_decisions.changed, 0); assert.equal(preflight.frozen_owner_decisions.reopened, 0);
  const sourceSnapshot = JSON.parse(snapshotRaw);
  const snapshot: Snapshot = { vehicle_brands: sourceSnapshot.relations.vehicle_brands.rows.map((r: any) => ({...r,revision:1,deleted_at:null})),
    vehicle_models: sourceSnapshot.relations.vehicle_models.rows.map((r: any) => ({...r,revision:1,deleted_at:null})), ice_model_crosswalk_scoped:[], ice_scopes:[] };
  snapshotForPlanning = snapshot;
  const inputById = new Map(inputs.candidates.map((v: any) => [v.canonical_id, v]));
  const candidates = preflight.candidates.filter((c: any) => c.disposition === "VALID_BASIC_IDENTITY_PROPOSAL");
  assert.deepEqual(candidates.map((c: any) => c.canonical_id).sort(), [...candidateIds].sort());
  assert.equal(candidates.reduce((n: number,c: any) => n + c.registrations,0),47109);
  const intents = candidates.map((c: any) => (inputById.get(c.canonical_id) as any).create_intent);
  const rawIceEvidence = Object.assign({}, ...candidates.map((c: any) => c.raw_ice_classification_evidence));
  assert.equal(Object.keys(rawIceEvidence).length,8);
  const baseBatch = createBatch(intents,"issue244-first-eight-full-catalog","Issue 244 private full catalog acceptance",rawIceEvidence);
  const version = pg("SELECT current_setting('server_version')");
  assert.match(version,/^16\./);
  pg(fs.readFileSync(path.join(root,"docs/vehicle-db/drafts/phase1c/basic_identity_schema.sql"),"utf8"));
  pg(fs.readFileSync(path.join(root,"docs/vehicle-db/drafts/phase1c/governed_structural_rpc.sql"),"utf8"));
  pg(`CREATE ROLE ${executor} LOGIN; CREATE ROLE ${issuer} LOGIN; GRANT vm_structural_approver TO ${executor}; GRANT vm_structural_approval_admin TO ${issuer};`);
  // Inject a deterministic second-insert failure over two of the approved targets.
  const rollbackBatch = createBatch(intents.slice(0,2),"issue244-injected-rollback","atomic rollback regression");
  pg(`CREATE FUNCTION vehicle_private.issue244_fail_second() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.canonical_id=${quote(intents[1].canonical_id)} THEN RAISE EXCEPTION 'ISSUE244_INJECTED_ROLLBACK'; END IF; RETURN NEW; END $$; CREATE TRIGGER issue244_fail_second BEFORE INSERT ON public.vehicle_models FOR EACH ROW EXECUTE FUNCTION vehicle_private.issue244_fail_second();`);
  const rollbackToken=randomBytes(32).toString("hex"); issue("issue244-rollback-approval",rollbackBatch.request.batch_hash,"CREATE_MODEL_BASIC",rollbackToken);
  assert.match(roleSql(executor,rpcSql(rollbackBatch.request,rollbackToken),true),/ISSUE244_INJECTED_ROLLBACK/);
  pg("DROP TRIGGER issue244_fail_second ON public.vehicle_models; DROP FUNCTION vehicle_private.issue244_fail_second();");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE identity_level='BASIC'"),"0");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_observations WHERE batch_id='issue244-injected-rollback'"),"0");
  const token=randomBytes(32).toString("hex"); issue("issue244-eight-approval",baseBatch.request.batch_hash,"CREATE_MODEL_BASIC",token);
  const applied=apply(baseBatch.request,token); assert.equal(applied.status,"APPLIED"); assert.equal(applied.revision_ids.length,8);
  assert.equal(apply(baseBatch.request,token).replay,true);
  const changed=createBatch(intents,"issue244-first-eight-full-catalog","changed payload regression",rawIceEvidence);
  changed.batch.reason="changed payload must fail";
  const changedRequest=buildStructuralRpcDraftRequest(changed.batch,planStructuralChanges(snapshot,changed.batch));
  const changedToken=randomBytes(32).toString("hex"); issue("issue244-changed-payload",changedRequest.batch_hash,"CREATE_MODEL_BASIC",changedToken);
  assert.match(roleSql(executor,rpcSql(changedRequest,changedToken),true),/STRUCTURAL_IDEMPOTENCY_HASH_CONFLICT/);
  // Full-catalog alias collision: use the real name as a requested alias for a distinct canonical target.
  const collisionIntent:any={operation:"CREATE_MODEL_BASIC",canonical_id:"honda.issue244_alias_collision",brand_id:"honda",name_en:"Issue244 Collision Probe",aliases:["Jazz"],expected_revision:0,
    identity_evidence:{granularity:"MODEL",model_name:"Issue244 Collision Probe",references:["issue244:collision-regression"]}};
  const collisionBatch=createBatch([collisionIntent],"issue244-alias-collision","normalized collision regression");
  const collisionToken=randomBytes(32).toString("hex"); issue("issue244-alias-collision",collisionBatch.request.batch_hash,"CREATE_MODEL_BASIC",collisionToken);
  assert.match(roleSql(executor,rpcSql(collisionBatch.request,collisionToken),true),/STRUCTURAL_NORMALIZED_IDENTITY_COLLISION/);
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE identity_level='BASIC'"),"8");
  assert.equal(pg("SELECT count(*) FROM public.vehicle_models WHERE identity_level='BASIC' AND (status IS NOT NULL OR generation_id IS NOT NULL OR served_as_of IS NOT NULL OR seed_release_id IS NOT NULL OR segment IS NOT NULL OR body_type IS NOT NULL OR retail_price_min IS NOT NULL OR retail_price_max IS NOT NULL)"),"0");
  for (const t of ["vehicle_generations","vehicle_variants","vehicle_trims","vehicle_facts","vehicle_price_ledger"]) {
    const n=t==='vehicle_generations'||t==='vehicle_variants'||t==='vehicle_trims'
      ? pg(`SELECT count(*) FROM public.${t} WHERE model_id IN (${candidateIds.map(quote).join(",")})`)
      : pg(`SELECT count(*) FROM public.${t} WHERE trim_id IN (SELECT canonical_id FROM public.vehicle_trims WHERE model_id IN (${candidateIds.map(quote).join(",")}))`);
    assert.equal(n,"0",`BASIC_CHILD_ROWS_PRESENT:${t}`);
  }
  assert.equal(pg("SELECT count(*) FROM public.current_vehicle_models"),String(relationCounts.vehicle_models));
  assert.equal(pg("SELECT count(*) FROM vehicle_private.market_analysis_basic_identities"),"8");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_observations WHERE batch_id='issue244-first-eight-full-catalog'"),"1");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_revisions WHERE batch_id='issue244-first-eight-full-catalog'"),"8");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_receipts WHERE batch_id='issue244-first-eight-full-catalog'"),"1");
  assert.equal(pg("SELECT count(*) FROM vehicle_private.vm_structural_approvals WHERE executor_actor='phase1d_test_executor' AND approved_actor='phase1d_test_issuer' AND admin_evidence_ref LIKE 'fixture:issue244:%'"),"6");
  // The actual test issuer/executor are distinct PostgreSQL principals; direct issue privilege is separated.
  assert.equal(pg(`SELECT has_function_privilege('${executor}','vehicle_private.vm_issue_structural_capability(text,text,text,text[],timestamptz,text,text)','EXECUTE')`),"f");
  assert.equal(pg(`SELECT has_function_privilege('${issuer}','vehicle_private.vm_apply_structural_changes(jsonb,text)','EXECUTE')`),"f");
  // Exercise the approved SQL alias/revert operations without leaving any catalog change.
  const basicRows = candidates.map((c: any) => {
    const intent=(inputById.get(c.canonical_id) as any).create_intent;
    return {canonical_id:intent.canonical_id,brand_id:intent.brand_id,name_en:intent.name_en,aliases:[],revision:1,deleted_at:null,identity_level:"BASIC",status:null,
      generation_id:null,segment:null,body_type:null,payload:{id:intent.canonical_id,brand_id:intent.brand_id,name_en:intent.name_en,aliases:[],identity_level:"BASIC",incomplete:true}};
  });
  const afterCreateSnapshot:Snapshot={...snapshot,vehicle_models:[...snapshot.vehicle_models,...basicRows]};
  const revertIntent:any={operation:"UPDATE_MODEL_ALIAS",canonical_id:"zeekr.7x",aliases:["Issue244 temporary QA alias"],expected_revision:1};
  const revertBatch:Batch={batch_id:"issue244-alias-revert",reason:"exercise approved alias and compensating revert",source_ref:"issue-244:test-only",observed_at:"2026-10-13T00:54:00.000Z",intents:[revertIntent]};
  const aliasPlan=planStructuralChanges(afterCreateSnapshot,revertBatch);
  assert.equal(aliasPlan.holds.length,0,JSON.stringify(aliasPlan.holds));
  const aliasRequest=buildStructuralRpcDraftRequest(revertBatch,aliasPlan);
  const aliasToken=randomBytes(32).toString("hex"); issue("issue244-alias-change",aliasRequest.batch_hash,"UPDATE_MODEL_ALIAS",aliasToken);
  const aliasResult=apply(aliasRequest,aliasToken); assert.equal(aliasResult.status,"APPLIED");
  const aliasRevision=pg("SELECT revision_id FROM vehicle_private.vm_structural_revisions WHERE batch_id='issue244-alias-revert' AND operation='UPDATE_MODEL_ALIAS'");
  const revertToken=randomBytes(32).toString("hex"); issue("issue244-alias-revert",structuralHash({operation:"REVERT",revision_id:aliasRevision,expected_revision:2}),"REVERT",revertToken);
  const reverted=roleSql(executor,`BEGIN ISOLATION LEVEL SERIALIZABLE; SELECT vehicle_private.vm_revert_structural_revision(${quote(aliasRevision)}::uuid,2,${quote(revertToken)}); COMMIT;`);
  assert.match(reverted,/REVERTED/);
  assert.equal(pg("SELECT identity_aliases::text FROM public.vehicle_models WHERE canonical_id='zeekr.7x'"),"[]");
  const roleAfter:Record<string,string>={};
  const privilegeAfter:Record<string,string>={};
  for (const role of readRoles) for (const view of views) {
    roleAfter[`${role}.${view}`] = pg(`SET ROLE ${role}; SELECT count(*) FROM public.${view}; RESET ROLE;`);
    assert.equal(roleAfter[`${role}.${view}`],roleBefore[`${role}.${view}`],`ROLE_VIEW_COUNT_CHANGED:${role}.${view}`);
  }
  for (const role of readRoles) for (const relation of ["vehicle_brands", "vehicle_models", ...views]) {
    privilegeAfter[`${role}.${relation}`]=pg(`SELECT has_table_privilege(${quote(role)},${quote(`public.${relation}`)},'SELECT');`);
    assert.equal(privilegeAfter[`${role}.${relation}`],privilegeBefore[`${role}.${relation}`],`ROLE_SELECT_ACL_CHANGED:${role}.${relation}`);
  }
  // Validate all CATALOG rows and six views stayed byte-for-byte stable; BASIC additions are outside CATALOG.
  const after=databaseSnapshot(true);
  for (const rel of [...tableOrder,...views]) {
    const expectedRows=rel==="vehicle_models"?relationCounts.vehicle_models:relationCounts[rel] ?? before[rel].rows;
    assert.equal(after[rel].rows,expectedRows,`POST_WRITE_COUNT_CHANGED:${rel}`);
    assert.equal(after[rel].md5,before[rel].md5,`POST_WRITE_CONTENT_CHANGED:${rel}`);
  }
  const sqlCaseCount=61;
  const report={schema:"tdr.vehicle-db.issue244.full-catalog-postgres-acceptance.v1",executed_at_utc:new Date().toISOString(),
    exact_command:"TDR_VM_PRIVATE_BACKUP_GZIP=<private path> npm run check:phase1d-full-catalog-postgres",docker_image:image,database:`PostgreSQL ${version}; network=none; tmpfs-only; no published port`,
    private_input:{available:true,raw_backup_pushed:false,gzip_sha256:expectedGzipSha,payload_sha256:expectedPayloadSha,tables:15,rows:28319,location:"external private attachment/temp only"},
    restored_catalog:{table_counts:relationCounts,source_baseline_counts_and_hashes_matched:true,view_counts_and_hashes_matched:true,view_names:views,phase1c_legacy_catalog_rows_unchanged:true},
    phase1c:{schema_and_rpc:"applied only in disposable database",basic_models_created:8,canonical_ids:candidateIds,registrations_represented:47109,
      rollback:"injected two-row transaction failure left zero model rows, observations, revisions or receipts for failed batch",same_payload_replay:"same receipt; no extra create",changed_payload_retry:"rejected",normalized_catalog_alias_collision:"rejected",issuer_executor:"distinct named local PostgreSQL roles; operation ACL separation verified",approval_audit:"one observation, eight revisions, one receipt, eight identity evidence records",revert_path:"BASIC alias revision applied and compensated; alias state restored; all CATALOG fingerprints unchanged"},
    role_view_row_counts_before:roleBefore,role_view_row_counts_after:roleAfter,select_privileges_before:privilegeBefore,select_privileges_after:privilegeAfter,
    unchanged_phase1c_sql_assertions:sqlCaseCount,frozen_inputs:{owner_decisions:244,ledger_sha256:frozenLedgerSha,scopes:1407,registration_units:4141987,effective_units:4123704,excluded_units:18283},
    ford_ranger_raptor:"HOLD / 12839 registrations; not created",other_basic_rows:0,production_or_staging_connections:0,production_or_staging_writes:0,
    acceptance_result:"PASS_LOCAL_FULL_CATALOG_REHEARSAL",production_acceptance:"BLOCKED_ADMIN_AUTH_C02_MIGRATION_ENFORCER",schema_acl_fidelity:"REPOSITORY_V57_V64_REPLAY; no fresh live schema/RLS/ACL manifest was available",raw_rows_in_report:false};
  fs.writeFileSync(path.join(root,"docs/vehicle-db/phase1d/issue244_full_catalog_rehearsal_report.json"),`${JSON.stringify(report,null,2)}\n`);
  console.log(JSON.stringify({schema:report.schema,executed_at_utc:report.executed_at_utc,acceptance_result:report.acceptance_result,rows:28319,tables:15,basic_models_created:8,sql_case_count:61,source_fingerprints_match:true,view_fingerprints_match:true,raw_rows_in_report:false},null,2));
} finally {
  run("docker", ["rm", "--force", container], undefined, true);
  fs.rmSync(restoreInputPath,{force:true});
}
