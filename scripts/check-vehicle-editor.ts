// Canonical Vehicle Editor (/admin/vehicles/[modelId]) regression tests.
// Same two-layer convention as the rest of scripts/check-*.ts:
//   - lib/spec-field-registry.ts, lib/canonical-command-builder.ts and
//     lib/edit-proposal-token.ts carry zero "@/" alias imports, so this
//     script loads and *executes* them directly with node
//     --experimental-strip-types and asserts on real return values.
//   - Files that need Next.js (server actions, pages, nav) are checked by
//     source-text regression, the same way check-eco-trim-admin.ts /
//     check-retail-lifecycle-review.ts test their own "@/"-aliased actions.
import fs from "node:fs";

process.env.ADMIN_SESSION_SECRET = process.env.ADMIN_SESSION_SECRET || "test-secret-at-least-16-bytes-long";

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
  buildModelGenerationBatch, buildMarketTrimBatch, buildSpecFactBatch,
  diffPatch, findDuplicateMarketTrim, isStaleRelease, normalizedTrimName,
} = await import("../lib/canonical-command-builder.ts");
const { signEditProposal, verifyEditProposal } = await import("../lib/edit-proposal-token.ts");

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

console.log("\ncommand builder — spec facts never turn missing data into a false zero/default");
{
  for (const state of ["UNKNOWN", "NOT_AVAILABLE", "NOT_APPLICABLE"] as const) {
    const command = buildSpecFactBatch({
      batchId: `b-${state}`, year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "review",
      evidence: { sourceKind: "ADMIN", reviewedAt: "2026-01-01" },
      trimId: "trim1", fieldKey: "powertrain.max_power_kw", valueState: state,
      value: 999, unit: "kW", // deliberately supplied to prove the builder still nulls it out
    }).payload.commands[0] as any;
    check(`${state} forces value to null regardless of args.value`, command.payload.value, null);
    check(`${state} forces unit to empty string`, command.payload.unit, "");
  }
  const known = buildSpecFactBatch({
    batchId: "b-known", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "review",
    evidence: { sourceKind: "OEM", sourceRef: "https://oem.example/spec", reviewedAt: "2026-01-01" },
    trimId: "trim1", fieldKey: "powertrain.max_power_kw", valueState: "KNOWN", value: 150, unit: "kW",
  }).payload.commands[0] as any;
  check("KNOWN carries the actual value", known.payload.value, 150);
  check("KNOWN carries the field's canonical unit", known.payload.unit, "kW");
  check("APPEND_SPEC targets the trim as canonical_id", known.canonical_id, "trim1");
}

console.log("\ncommand builder — evidence is recorded even though batch source.kind stays ADMIN");
{
  const { payload } = buildMarketTrimBatch({
    batchId: "b3", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "new trim",
    evidence: { sourceKind: "OEM", sourceRef: "https://oem.example/page", reviewedAt: "2026-01-01" },
    canonicalModelId: "m.x", brand: { id: "m", nameEn: "M" }, generationCode: "g1",
    trim: { name: "X", powertrain: "ICE" },
  });
  check("evidence URL is carried as source.ref", payload.source.ref, "https://oem.example/page");
  ok("reason is tagged with the evidence kind when it is not a plain admin note", payload.reason.startsWith("[OEM evidence]"));
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

console.log("\nedit-proposal-token — signed round trip, tamper and expiry rejection");
{
  const proposal = {
    kind: "MODEL_GENERATION" as const, modelId: "toyota.yaris_ativ", pageReleaseId: "rel-1",
    batchPayload: { schema_version: 1 as const, batch_id: "b", year: 2026, submitted_at: "2026-01-01T00:00:00Z", source: { kind: "ADMIN" }, reason: "r", commands: [] },
    diff: [], reason: "r", evidence: { sourceKind: "ADMIN" as const, reviewedAt: "2026-01-01" }, actor: "tester",
  };
  const token = signEditProposal(proposal);
  const verified = verifyEditProposal(token);
  check("a freshly signed token verifies and round-trips the modelId", verified?.modelId, "toyota.yaris_ativ");
  ok("a tampered token is rejected", verifyEditProposal(token.slice(0, -1) + (token.at(-1) === "0" ? "1" : "0")) === null);
  ok("garbage input is rejected, not thrown", verifyEditProposal("not-a-token") === null);
  ok("an empty token is rejected", verifyEditProposal("") === null);
}

console.log("\nsource-text regression — server actions, pages and nav wiring");
{
  const actions = fs.readFileSync("app/admin/vehicle-editor-actions.ts", "utf8");
  ok("prepareModelGenerationEdit is admin-gated", /export async function prepareModelGenerationEdit[\s\S]{0,200}isAdmin\(\)/.test(actions));
  ok("prepareMarketTrimEdit is admin-gated", /export async function prepareMarketTrimEdit[\s\S]{0,200}isAdmin\(\)/.test(actions));
  ok("prepareSpecFactEdit is admin-gated", /export async function prepareSpecFactEdit[\s\S]{0,200}isAdmin\(\)/.test(actions));
  ok("confirmEditProposal is admin-gated", /export async function confirmEditProposal[\s\S]{0,200}isAdmin\(\)/.test(actions));
  ok("every prepare action checks the release fingerprint before building a command", (actions.match(/assertNotStale\(/g) || []).length >= 3);
  ok("confirm re-checks staleness against live state before enqueueing, not just the token's own claim", /liveModelReleaseId\(proposal\.modelId\)[\s\S]{0,200}assertNotStale/.test(actions));
  ok("MarketTrim create/edit requires evidence ref (requireRef: true)", /prepareMarketTrimEdit[\s\S]*?readEvidence\(formData, \{ requireRef: true \}\)/.test(actions));
  ok("Spec KNOWN facts require evidence ref; dispositions do not", /requireRef: valueState === "KNOWN"/.test(actions));
  ok("duplicate MarketTrim identity is checked before building the command", /findDuplicateMarketTrim\(/.test(actions));
  ok("a MarketTrim edit is rejected if the trim is not already under this model (no wrong-model attach)", /workspace\.trims\.some\(\(row\) => row\.canonicalId === existingTrimId\)/.test(actions));
  ok("a spec fact edit is rejected if the trim does not belong to this model", /trim\.modelId !== modelId/.test(actions));
  ok("the only write path is enqueueCanonicalInputBatch — no direct Supabase .update/.insert on canonical tables", !/adminDb\(\)/.test(actions));
  ok("nothing in the actions file targets current_vehicle_ or canonical_ tables directly", !/\.from\(["'`](current_|canonical_)/.test(actions));
}
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
{
  const workspace = fs.readFileSync("app/admin/(secure)/vehicles/[modelId]/page.tsx", "utf8");
  ok("workspace page links out to the existing Price Bench instead of embedding price editing", /Price Bench/.test(workspace) && /vehicle-input\?model=/.test(workspace));
  ok("workspace page links out to Retail lifecycle review", /retail-lifecycle\?model=/.test(workspace));
  ok("workspace page links out to Editorial when a TDR model crosswalk exists", /models\/\$\{model\.tdrModelId\}\/edit/.test(workspace));
  ok("spec field <select> is rendered from the loaded registry, not a hardcoded list of options", /groups\.entries\(\)/.test(workspace) && !/<option value="powertrain\.max_power_kw"/.test(workspace));
  ok("generation code is displayed but not an editable form field (identity-preserving)", !/name="code"/.test(workspace) && !/name="generation_code"/.test(workspace));
}
{
  const review = fs.readFileSync("app/admin/(secure)/vehicles/[modelId]/review/page.tsx", "utf8");
  ok("review page renders a Current vs Proposed diff table", /Current/.test(review) && /Proposed/.test(review));
  ok("review page exposes the raw canonical JSON as an optional/secondary view", /<details/.test(review) && /Raw canonical command JSON/.test(review));
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
