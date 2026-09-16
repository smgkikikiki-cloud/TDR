// Canonical Vehicle Editor (/admin/vehicles/[modelId]) regression tests.
// Same two-layer convention as the rest of scripts/check-*.ts:
//   - lib/spec-field-registry.ts, lib/canonical-command-builder.ts and
//     lib/admin-form.ts carry zero "@/" alias imports, so this script loads
//     and *executes* them directly with node --experimental-strip-types and
//     asserts on real return values.
//   - Files that need Next.js/Supabase (server actions, the edit-session
//     store, pages, nav, the migration file) are checked by source-text
//     regression, the same way check-eco-trim-admin.ts /
//     check-retail-lifecycle-review.ts test their own "@/"-aliased actions.
import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}
function ok(name: string, condition: boolean) {
  check(name, condition, true);
}

const {
  loadSpecFieldRegistry, specFieldByKey, fieldAppliesToPowertrain, groupSpecFields,
} = await import("../lib/spec-field-registry.ts");
const {
  buildModelGenerationBatch, buildMarketTrimBatch, buildSpecDraftBatch, diffSpecDraft,
  diffPatch, findDuplicateMarketTrim, isStaleRelease, normalizedTrimName, applySourceRefEdits,
} = await import("../lib/canonical-command-builder.ts");
const { evidenceUrl } = await import("../lib/admin-form.ts");

console.log("spec field registry — reads the real canonical registry.json, not a hardcoded copy");
{
  const fields = loadSpecFieldRegistry(2026);
  ok("2026 registry has a substantial field list", fields.length > 40);
  const groups = groupSpecFields(fields);
  ok("fields are grouped (identity/dimensions/powertrain/battery/safety/...)", groups.size >= 8);
  const power = specFieldByKey(2026, "powertrain.max_power_kw");
  ok("known field resolves with unit + group", Boolean(power && power.canonicalUnit === "kW" && power.group === "powertrain"));
  ok("unknown field key resolves to null (never fabricated)", specFieldByKey(2026, "not.a.real.field") === null);
  const displacement = specFieldByKey(2026, "engine.displacement_cc")!;
  ok("engine displacement is scoped to combustion/hybrid powertrains", !fieldAppliesToPowertrain(displacement, "BEV"));
  ok("engine displacement applies to ICE", fieldAppliesToPowertrain(displacement, "ICE"));
  const seats = specFieldByKey(2026, "vehicle.seats")!;
  ok("a field with no applicable_powertrains list is universal", fieldAppliesToPowertrain(seats, "BEV") && fieldAppliesToPowertrain(seats, "ICE"));
  ok("an old catalog year with no registry falls back instead of throwing", loadSpecFieldRegistry(2021).length > 0);
}

console.log("\ncommand builder — UPSERT_MODEL_BUNDLE for model/generation edits");
{
  const { payload } = buildModelGenerationBatch({
    batchId: "admin-vehicle-model-test", year: 2026, submittedAt: "2026-01-01T00:00:00Z",
    reason: "fix taxonomy", evidence: { sourceKind: "ADMIN", reviewedAt: "2026-01-01" },
    canonicalModelId: "toyota.yaris_ativ",
    brand: { id: "toyota", nameEn: "Toyota" },
    generationCode: "MXPA10",
    modelPatch: { name_en: "Yaris Ativ" },
    generationPatch: {},
  });
  ok("schema_version 1", payload.schema_version === 1);
  ok("batch source.kind is always ADMIN (enqueueCanonicalInputBatch requires it)", payload.source.kind === "ADMIN");
  const command = payload.commands[0] as any;
  ok("operation is UPSERT_MODEL_BUNDLE", command.operation === "UPSERT_MODEL_BUNDLE");
  check("canonical_id is the caller-supplied stable id, never derived from the new name", command.canonical_id, "toyota.yaris_ativ");
  ok("untouched body_type is absent from the model patch (sibling fields preserved)", !("body_type" in command.payload.model));
  check("generation code is always re-submitted unchanged to preserve generation identity", command.payload.generation.code, "MXPA10");
}

console.log("\ncommand builder — MarketTrim create vs edit preserves identity");
{
  const created = buildMarketTrimBatch({
    batchId: "b1", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "new trim",
    evidence: { sourceKind: "OEM", sourceRef: "https://oem.example/page", reviewedAt: "2026-01-01" },
    canonicalModelId: "jaecoo.jaecoo_5_ev", brand: { id: "jaecoo", nameEn: "Jaecoo" }, generationCode: "j5",
    trim: { name: "Max Plus", powertrain: "BEV" },
  }).payload.commands[0] as any;
  ok("a new trim carries no canonical_id (worker assigns identity from generation+name+powertrain)", !("canonical_id" in created.payload.trims[0]));

  const edited = buildMarketTrimBatch({
    batchId: "b2", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "correct spec",
    evidence: { sourceKind: "OEM", sourceRef: "https://oem.example/page", reviewedAt: "2026-01-01" },
    canonicalModelId: "jaecoo.jaecoo_5_ev", brand: { id: "jaecoo", nameEn: "Jaecoo" }, generationCode: "j5",
    existingTrimId: "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
    // Real callers (app/admin/vehicle-editor-actions.ts) only ever assign a
    // key when a value was actually parsed from the form -- an untouched
    // field is never present, not present-with-value-undefined.
    trim: { name: "Max Plus", powertrain: "BEV" },
  }).payload.commands[0] as any;
  check("editing an existing trim always carries its stable canonical_id", edited.payload.trims[0].canonical_id, "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev");
  ok("an omitted (untouched) field is absent from the patch, not overwritten with undefined/null", !("engine_cc" in edited.payload.trims[0]));
}

console.log("\ncommand builder — duplicate MarketTrim identity detection never auto-merges");
{
  const existing = [
    { canonicalId: "t1", generationId: "gen1", name: "Max Plus", powertrain: "BEV" },
    { canonicalId: "t2", generationId: "gen1", name: "Comfort", powertrain: "ICE" },
    { canonicalId: "t3", generationId: "gen2", name: "Max Plus", powertrain: "BEV" },
  ];
  const dup = findDuplicateMarketTrim(existing, { generationId: "gen1", name: "  MAX   plus ", powertrain: "bev" });
  check("same generation + powertrain + normalized name is flagged as a duplicate", dup?.canonicalId, "t1");
  ok("a different generation with the same name/powertrain is not a duplicate", findDuplicateMarketTrim(existing, { generationId: "gen3", name: "Max Plus", powertrain: "BEV" }) === null);
  ok("a different powertrain in the same generation is not a duplicate", findDuplicateMarketTrim(existing, { generationId: "gen1", name: "Max Plus", powertrain: "ICE" }) === null);
  ok("editing a trim against itself (excludeCanonicalId) is not flagged as its own duplicate", findDuplicateMarketTrim(existing, { generationId: "gen1", name: "Max Plus", powertrain: "BEV", excludeCanonicalId: "t1" }) === null);
  check("normalizedTrimName folds case/spacing/punctuation", normalizedTrimName("  Max-Plus!! "), "max plus");
}

console.log("\ncommand builder — a multi-field spec draft compiles into ONE batch, one command per touched field");
{
  const evidence = { sourceKind: "OEM" as const, sourceRef: "https://oem.example/spec-sheet", reviewedAt: "2026-01-01" };
  const entries = [
    { fieldKey: "powertrain.max_power_kw", labelForDiff: "Maximum power", valueState: "KNOWN" as const, value: 150, unit: "kW", evidence },
    { fieldKey: "powertrain.max_torque_nm", labelForDiff: "Maximum torque", valueState: "KNOWN" as const, value: 310, unit: "Nm", evidence },
    { fieldKey: "powertrain.drivetrain", labelForDiff: "Drivetrain", valueState: "KNOWN" as const, value: "AWD", unit: "" },
    { fieldKey: "battery.gross_capacity_kwh", labelForDiff: "Gross battery capacity", valueState: "NOT_APPLICABLE" as const, value: null, unit: "kWh" },
    { fieldKey: "vehicle.wheelbase_mm", labelForDiff: "Wheelbase", valueState: "UNKNOWN" as const, value: null, unit: "mm" },
  ];
  const { payload } = buildSpecDraftBatch({
    batchId: "admin-vehicle-spec-draft-test", year: 2026, submittedAt: "2026-01-01T00:00:00Z",
    reason: "Official spec sheet for this trim", evidence, trimId: "acme.testmodel.gen1.trim.trim_a", entries,
  });
  check("one batch", payload.schema_version, 1);
  check("one APPEND_SPEC command per entry, five entries -> five commands", payload.commands.length, 5);
  ok("every command targets the same trim", payload.commands.every((c: any) => c.canonical_id === "acme.testmodel.gen1.trim.trim_a" && c.operation === "APPEND_SPEC"));
  ok("batch reason is tagged with the draft's evidence kind once, not per field", payload.reason.startsWith("[OEM evidence]") && payload.commands.filter((c: any) => "reason" in c).length === 0);

  const power = payload.commands[0] as any;
  check("KNOWN entry carries its value and unit", power.payload.value, 150);
  check("KNOWN entry carries the field's canonical unit", power.payload.unit, "kW");
  check("KNOWN entry with its own evidence override uses that source_ref", power.payload.source_ref, "https://oem.example/spec-sheet");

  const drivetrain = payload.commands[2] as any;
  check("an entry without its own evidence falls back to the draft's default evidence", drivetrain.payload.source_ref, "https://oem.example/spec-sheet");

  const notApplicable = payload.commands[3] as any;
  check("NOT_APPLICABLE never carries a value even if one was passed in", notApplicable.payload.value, null);
  check("NOT_APPLICABLE never carries a unit", notApplicable.payload.unit, "");

  const unknown = payload.commands[4] as any;
  check("UNKNOWN never carries a value", unknown.payload.value, null);

  let threw = false;
  try { buildSpecDraftBatch({ batchId: "empty", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "r", evidence, trimId: "t", entries: [] }); }
  catch { threw = true; }
  ok("an empty draft cannot be compiled into a batch", threw);
}

console.log("\ncommand builder — spec draft diff shows current vs proposed per field, distinguishing UNKNOWN/NOT_AVAILABLE/NOT_APPLICABLE/KNOWN");
{
  const evidence = { sourceKind: "ADMIN" as const, reviewedAt: "2026-01-01" };
  const currentByField = {
    "powertrain.max_power_kw": { value_state: "KNOWN", value: 120 },
    "battery.gross_capacity_kwh": { value_state: "UNKNOWN", value: null },
  };
  const entries = [
    { fieldKey: "powertrain.max_power_kw", labelForDiff: "Maximum power", valueState: "KNOWN" as const, value: 150, unit: "kW" },
    { fieldKey: "powertrain.max_torque_nm", labelForDiff: "Maximum torque", valueState: "KNOWN" as const, value: 310, unit: "Nm" },
    { fieldKey: "battery.gross_capacity_kwh", labelForDiff: "Gross battery capacity", valueState: "NOT_APPLICABLE" as const, value: null, unit: "" },
  ];
  const diff = diffSpecDraft(currentByField, entries);
  check("one diff row per drafted field", diff.length, 3);
  const power = diff.find((row) => row.field === "powertrain.max_power_kw")!;
  ok("a field whose value actually changed (120 -> 150) is marked changed", power.changed);
  const torque = diff.find((row) => row.field === "powertrain.max_torque_nm")!;
  check("a field with no prior fact defaults its current side to UNKNOWN/null, not a fabricated zero", torque.current, { value_state: "UNKNOWN", value: null });
  ok("a brand-new fact is marked changed", torque.changed);
  const battery = diff.find((row) => row.field === "battery.gross_capacity_kwh")!;
  ok("UNKNOWN -> NOT_APPLICABLE is still a real, visible change (both are 'no value' but mean different things)", battery.changed);
}

console.log("\ncommand builder — structured source-ref add/remove compiles to the exact shape MarketTrim.source_refs already uses");
{
  const existing = { ecosticker: ["uuid-1"], official_omodajaecoo: ["https://oem.example/old"] };
  const afterRemove = applySourceRefEdits(existing, { remove: [{ kind: "official_omodajaecoo", url: "https://oem.example/old" }], add: [] });
  check("removing the only url under a kind drops that kind entirely", afterRemove, { ecosticker: ["uuid-1"] });

  const afterAdd = applySourceRefEdits(existing, { remove: [], add: [{ kind: "owner_directory", url: "https://oem.example/new" }] });
  check("adding a new kind creates it", afterAdd, { ecosticker: ["uuid-1"], official_omodajaecoo: ["https://oem.example/old"], owner_directory: ["https://oem.example/new"] });

  const dedup = applySourceRefEdits(existing, { remove: [], add: [{ kind: "ecosticker", url: "uuid-1" }] });
  check("re-adding an existing (kind, url) pair does not duplicate it", dedup.ecosticker, ["uuid-1"]);

  const both = applySourceRefEdits(existing, {
    remove: [{ kind: "ecosticker", url: "uuid-1" }],
    add: [{ kind: "ecosticker", url: "uuid-2" }],
  });
  check("remove and add can target the same kind in one edit", both.ecosticker, ["uuid-2"]);

  ok("empty existing + no edits produces an empty object, not undefined/null", JSON.stringify(applySourceRefEdits({}, { remove: [], add: [] })) === "{}");
}

console.log("\nadmin-form — evidenceUrl rejects malformed source references (executed for real, not just grepped)");
{
  let threw = false;
  try { evidenceUrl("not a url"); } catch { threw = true; }
  ok("a non-URL string is rejected", threw);
  threw = false;
  try { evidenceUrl("javascript:alert(1)"); } catch { threw = true; }
  ok("a non-http(s) scheme is rejected", threw);
  check("a well-formed https URL round-trips", evidenceUrl("https://example.com/page"), "https://example.com/page");
}

console.log("\ndiffPatch — only fields the admin actually touched appear in the diff");
{
  const rows = diffPatch({ name_en: "Old", body_type: "SEDAN" }, { name_en: "New" }, { name_en: "Name" });
  check("only the touched key produces a diff row", rows.length, 1);
  ok("the touched row is marked changed", rows[0].changed);
  const same = diffPatch({ name_en: "Same" }, { name_en: "Same" }, { name_en: "Name" });
  ok("resubmitting the same value is not marked changed", !same[0].changed);
}

console.log("\nstale-edit protection");
{
  ok("same release_id is not stale", !isStaleRelease("rel-1", "rel-1"));
  ok("a different release_id is stale", isStaleRelease("rel-1", "rel-2"));
  ok("a missing page fingerprint never blocks (treated as not-yet-established, not as stale)", !isStaleRelease("", "rel-2"));
}

console.log("\nsource-text regression — the token-in-URL design is fully removed");
{
  ok("lib/edit-proposal-token.ts no longer exists", !fs.existsSync("lib/edit-proposal-token.ts"));
  ok("the old query-token review page no longer exists", !fs.existsSync("app/admin/(secure)/vehicles/[modelId]/review/page.tsx"));
  ok("the new review route is a path-segment proposal id, not a query string", fs.existsSync("app/admin/(secure)/vehicles/[modelId]/review/[proposalId]/page.tsx"));
}

console.log("\nsource-text regression — edit-session-store.ts enforces ownership and one-time consumption in Postgres, not just in JS");
{
  const store = fs.readFileSync("lib/edit-session-store.ts", "utf8");
  ok("proposal ids are high-entropy random tokens, not sequential/guessable", /randomBytes\(24\)/.test(store));
  ok("every load is scoped by actor in the query itself (ownership at the DB layer)", (store.match(/\.eq\("actor", actor\)/g) || []).length >= 4);
  ok("consumeProposal is one atomic conditional UPDATE (status PENDING_REVIEW -> CONSUMED), not read-then-write", /consumeProposal[\s\S]{0,400}status: "CONSUMED"[\s\S]{0,200}eq\("status", "PENDING_REVIEW"\)/.test(store));
  ok("consumeProposal also re-checks expiry in the same query", /consumeProposal[\s\S]{0,600}gt\("expires_at"/.test(store));
  ok("promoteDraftToProposal is conditioned on status='DRAFT' so a draft can only be promoted once", /promoteDraftToProposal[\s\S]{0,700}eq\("status", "DRAFT"\)/.test(store));
  ok("no function returns a partial/ambiguous success on a failed ownership/expiry check -- all return null or throw", !/return (data|row) as EditSessionRow;/.test(store));
}

console.log("\nsource-text regression — server actions: ownership, atomic consume-first ordering, admin gating");
{
  const actions = fs.readFileSync("app/admin/vehicle-editor-actions.ts", "utf8");
  for (const fn of [
    "prepareModelGenerationEdit", "prepareMarketTrimEdit", "addSpecDraftEntry", "removeSpecDraftEntry",
    "discardSpecDraft", "prepareSpecDraftReview", "confirmEditProposal",
  ]) {
    ok(`${fn} is admin-gated`, new RegExp(`export async function ${fn}[\\s\\S]{0,200}isAdmin\\(\\)`).test(actions));
  }
  ok("every proposal/draft is created or loaded against the authenticated editor's own name (requireEditor), never a shared fallback actor", !/\|\| "tdr-admin"/.test(actions));
  ok("confirmEditProposal consumes the proposal BEFORE checking staleness (atomicity first, so a double-submit can never both pass)", /const consumed = await consumeProposal\(proposalId, editor\.name\)[\s\S]{0,400}assertNotStale\(consumed\.pageReleaseId/.test(actions));
  ok("confirmEditProposal never enqueues without a successful consume", /if \(!consumed\) \{[\s\S]{0,200}throw new Error/.test(actions));
  ok("every prepare action checks the release fingerprint before building/staging a command", (actions.match(/assertNotStale\(/g) || []).length >= 4);
  ok("MarketTrim create/edit requires evidence ref (requireRef: true)", /prepareMarketTrimEdit[\s\S]*?readEvidence\(formData, \{ requireRef: true \}\)/.test(actions));
  ok("a KNOWN spec entry requires evidence ref; non-KNOWN dispositions do not", /requireRef: valueState === "KNOWN"/.test(actions));
  ok("duplicate MarketTrim identity is checked before building the command", /findDuplicateMarketTrim\(/.test(actions));
  ok("a MarketTrim edit is rejected if the trim is not already under this model (no wrong-model attach)", /workspace\.trims\.some\(\(row\) => row\.canonicalId === existingTrimId\)/.test(actions));
  ok("a spec draft entry is rejected if the trim does not belong to this model", /trim\.modelId !== modelId/.test(actions));
  ok("source-ref edits validate malformed URLs via evidenceUrl before building any command", /function readSourceRefEdits[\s\S]{0,1200}evidenceUrl\(/.test(actions));
  ok("source-ref kind free text is validated against a safe token pattern", /SOURCE_KIND_TOKEN/.test(actions));
  ok("only the entries actually staged in a draft become commands -- prepareSpecDraftReview refuses an empty draft", /if \(!draft\.draftEntries\.length\) throw/.test(actions));
  ok("the only write path is enqueueCanonicalInputBatch — no direct Supabase .update/.insert on canonical tables", !/adminDb\(\)/.test(actions));
  ok("nothing in the actions file targets current_vehicle_ or canonical_ tables directly", !/\.from\(["'`](current_|canonical_)/.test(actions));
}

console.log("\nsource-text regression — canonical-editor.ts remains read-only");
{
  const editor = fs.readFileSync("lib/canonical-editor.ts", "utf8");
  ok("canonical-editor.ts only ever selects from serving projections, never writes to them", !/\.(update|insert|upsert|delete)\(/.test(editor));
  ok("reads current_vehicle_models / current_market_trims / current_spec_facts projections", /current_vehicle_models/.test(editor) && /current_market_trims/.test(editor) && /current_spec_facts/.test(editor));
}
{
  const builder = fs.readFileSync("lib/canonical-command-builder.ts", "utf8");
  ok("MarketTrimFields never carries a price field (price stays owned by the Price Ledger)", !/price_thb|amount_thb/.test(builder));
  ok("no '@/' alias imports (keeps this module executable outside the bundler for tests)", !/from "@\//.test(builder));
}

console.log("\nsource-text regression — migration file for admin_edit_sessions is present, locked down, and not wired into any apply step");
{
  ok("migration file exists", fs.existsSync("supabase/migration_v35_admin_edit_sessions.sql"));
  const migration = fs.readFileSync("supabase/migration_v35_admin_edit_sessions.sql", "utf8");
  ok("RLS is enabled", /enable row level security/.test(migration));
  ok("public/anon/authenticated are explicitly revoked (same lockdown as canonical_input_batches)", /revoke all on table public\.admin_edit_sessions from public, anon, authenticated/.test(migration));
  ok("only service_role is granted access", /grant select, insert, update, delete on table public\.admin_edit_sessions to service_role/.test(migration));
  ok("no anon/authenticated grant appears anywhere in the file", !/grant[^;]*to (anon|authenticated)/.test(migration));
}

console.log("\nsource-text regression — workspace page: multi-spec draft UI, structured source refs, no JSON textarea for routine work");
{
  const workspace = fs.readFileSync("app/admin/(secure)/vehicles/[modelId]/page.tsx", "utf8");
  ok("the spec section supports adding multiple fields to one draft before review", /addSpecDraftEntry/.test(workspace) && /prepareSpecDraftReview/.test(workspace));
  ok("a pending draft entry can be individually removed", /removeSpecDraftEntry/.test(workspace));
  ok("a whole draft can be discarded", /discardSpecDraft/.test(workspace));
  ok("draft evidence is prefilled from the draft's own default (no retyping per field)", /draft\?\.defaultEvidence\?\.sourceRef/.test(workspace));
  ok("MarketTrim source refs use structured remove checkboxes, not a source_refs JSON textarea", /name="remove_source"/.test(workspace) && !/name="source_refs"/.test(workspace));
  ok("MarketTrim source refs can reuse a registered OEM evidence target by selection", /new_source_target_/.test(workspace));
  ok("workspace page links out to the existing Price Bench instead of embedding price editing", /Price Bench/.test(workspace) && /vehicle-input\?model=/.test(workspace));
  ok("workspace page links out to Retail lifecycle review", /retail-lifecycle\?model=/.test(workspace));
  ok("workspace page links out to Editorial (+ industry/production context) when a TDR model crosswalk exists", /models\/\$\{model\.tdrModelId\}\/edit/.test(workspace));
  ok("workspace has an explicit section nav across canonical/trims/specs/prices/lifecycle/editorial/evidence", /Vehicle workspace sections/.test(workspace));
  ok("spec field <select> is rendered from the loaded registry, not a hardcoded list of options", /groups\.entries\(\)/.test(workspace) && !/<option value="powertrain\.max_power_kw"/.test(workspace));
  ok("generation code is displayed but not an editable form field (identity-preserving)", !/name="code"/.test(workspace) && !/name="generation_code"/.test(workspace));
}
{
  const review = fs.readFileSync("app/admin/(secure)/vehicles/[modelId]/review/[proposalId]/page.tsx", "utf8");
  ok("review page loads the proposal by id via params, not by reading payload out of searchParams/query", /params: Promise<\{ modelId: string; proposalId: string \}>/.test(review) && !/searchParams/.test(review));
  ok("review page loads the proposal server-side through loadOwnedProposal (re-authenticates + ownership + expiry)", /loadOwnedProposal\(proposalId\)/.test(review));
  ok("review page renders a Current vs Proposed diff table", /Current/.test(review) && /Proposed/.test(review));
  ok("review page exposes the raw canonical JSON as an optional/secondary view", /<details/.test(review) && /Raw canonical command JSON/.test(review));
  ok("confirming submits only the opaque proposal_id, not the payload/diff/evidence/reason", /name="proposal_id" value={proposalId}/.test(review) && !/name="payload"/.test(review) && !/name="diff"/.test(review));
  ok("confirming submits through confirmEditProposal, the one path into the queue", /action={confirmEditProposal}/.test(review));
}
{
  const nav = fs.readFileSync("components/admin/AdminNav.tsx", "utf8");
  ok("Canonical Vehicle Editor is reachable from the admin nav", /\/admin\/vehicles/.test(nav));
}
{
  const queue = fs.readFileSync("lib/canonical-input-queue.ts", "utf8");
  ok("enqueueCanonicalInputBatch (the shared queue path) still enforces admin auth", /isAdmin\(\)/.test(queue));
}

console.log("\nbackward compatibility — existing admin benches untouched");
{
  ok("/admin/vehicle-input Advanced JSON textarea still present", /enqueueVehicleInput/.test(fs.readFileSync("app/admin/(secure)/vehicle-input/page.tsx", "utf8")));
  for (const file of [
    "app/admin/input-actions.ts", "app/admin/eco-trim-actions.ts", "app/admin/price-actions.ts",
    "app/admin/retail-lifecycle-actions.ts", "app/admin/trim-retail-lifecycle-actions.ts",
  ]) {
    ok(`${file} still exports its original server actions ("use server")`, fs.readFileSync(file, "utf8").startsWith('"use server"'));
  }
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall Canonical Vehicle Editor checks passed");
process.exit(failed ? 1 : 0);
