// Canonical Vehicle Editor (/admin/vehicles/[modelId]) regression tests.
// Two layers, same convention as the rest of scripts/check-*.ts:
//   - lib/canonical-command-builder.ts, lib/spec-field-registry.ts and
//     lib/admin-form.ts carry zero "@/" alias imports, so this script loads
//     and *executes* them and asserts on real return values.
//   - Files that need Next.js/Supabase (server actions, session store, pages,
//     migration) are checked by source-text regression.
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
  buildModelGenerationBatch, buildTrimEditBatch, diffTrimEdit, composeReason,
  diffPatch, findDuplicateMarketTrim, isStaleRelease, normalizedTrimName, applySourceRefEdits,
} = await import("../lib/canonical-command-builder.ts");

const EVIDENCE = { sourceKind: "OEM" as const, sourceRef: "https://oem.example/spec", reviewedAt: "2026-01-01" };
const TRIM_BASE = {
  batchId: "b-trim", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "update",
  evidence: EVIDENCE, canonicalModelId: "acme.testmodel", brand: { id: "acme", nameEn: "Acme" },
  generationCode: "gen1", existingTrimId: "acme.testmodel.gen1.trim.trim_a",
};

console.log("spec field registry — reads the real canonical registry.json, not a hardcoded copy");
{
  const fields = loadSpecFieldRegistry(2026);
  ok("2026 registry has a substantial field list", fields.length > 40);
  ok("fields are grouped", groupSpecFields(fields).size >= 8);
  const power = specFieldByKey(2026, "powertrain.max_power_kw");
  ok("known field resolves with unit + group", Boolean(power && power.canonicalUnit === "kW" && power.group === "powertrain"));
  ok("unknown field key resolves to null (never fabricated)", specFieldByKey(2026, "not.a.real.field") === null);
  const displacement = specFieldByKey(2026, "engine.displacement_cc")!;
  ok("engine displacement is scoped away from BEV", !fieldAppliesToPowertrain(displacement, "BEV"));
  ok("engine displacement applies to ICE", fieldAppliesToPowertrain(displacement, "ICE"));
  const seats = specFieldByKey(2026, "vehicle.seats")!;
  ok("a field with no applicable_powertrains list is universal", fieldAppliesToPowertrain(seats, "BEV") && fieldAppliesToPowertrain(seats, "ICE"));
  ok("an old catalog year with no registry falls back instead of throwing", loadSpecFieldRegistry(2021).length > 0);
}

console.log("\none trim = one batch: MarketTrim fields and comparable-spec facts travel together");
{
  const { payload } = buildTrimEditBatch({
    ...TRIM_BASE,
    trim: { name: "Max", powertrain: "BEV", seats: 5, tire_front: "235/55 R18" },
    specEntries: [
      { fieldKey: "powertrain.max_power_kw", labelForDiff: "Maximum power (kW)", valueState: "KNOWN", value: 150, unit: "kW" },
      { fieldKey: "powertrain.max_torque_nm", labelForDiff: "Maximum torque (Nm)", valueState: "KNOWN", value: 310, unit: "Nm" },
      { fieldKey: "safety.aeb", labelForDiff: "AEB", valueState: "KNOWN", value: true, unit: "" },
    ],
  });
  check("one batch carries the trim patch plus one command per spec fact", payload.commands.length, 4);
  const [trimCommand, ...specCommands] = payload.commands as any[];
  check("the trim patch is the first command", trimCommand.operation, "UPSERT_MODEL_BUNDLE");
  check("the trim keeps its stable canonical_id", trimCommand.payload.trims[0].canonical_id, "acme.testmodel.gen1.trim.trim_a");
  check("the trim's own fields ride in that command", trimCommand.payload.trims[0].tire_front, "235/55 R18");
  ok("every spec fact is its own APPEND_SPEC against the same trim", specCommands.every((c) => c.operation === "APPEND_SPEC" && c.canonical_id === "acme.testmodel.gen1.trim.trim_a"));
  check("a boolean spec keeps a real false/true, not a string", (specCommands[2] as any).payload.value, true);
  check("a numeric spec keeps its registry unit", (specCommands[0] as any).payload.value + "/" + (specCommands[0] as any).payload.unit, "150/kW");
  ok("batch source.kind stays ADMIN (the queue helper requires it)", payload.source.kind === "ADMIN");

  // SpecLedger rejects a fact with no fact_id outright, and resolves a
  // field's current value by taking the lexicographically last active fact.
  ok("every spec command carries a fact_id (SpecLedger requires one)", specCommands.every((c) => typeof c.payload.fact_id === "string" && c.payload.fact_id.length > 0));
  ok("every spec command carries its trim_id and field_key", specCommands.every((c) => c.payload.trim_id === "acme.testmodel.gen1.trim.trim_a" && typeof c.payload.field_key === "string"));
  ok("fact_ids are unique per field within one save", new Set(specCommands.map((c) => c.payload.fact_id)).size === specCommands.length);
}
{
  // A later save of the same field must out-sort the earlier one, or the
  // ledger would keep resolving to the stale value.
  const idAt = (submittedAt: string) => (buildTrimEditBatch({
    ...TRIM_BASE, submittedAt, trim: { name: "Max", powertrain: "BEV" },
    specEntries: [{ fieldKey: "powertrain.max_power_kw", labelForDiff: "Maximum power (kW)", valueState: "KNOWN", value: 150, unit: "kW" }],
  }).payload.commands[1] as any).payload.fact_id as string;
  const earlier = idAt("2026-01-01T00:00:00Z");
  const later = idAt("2026-06-01T00:00:00Z");
  ok("a later save produces a lexicographically greater fact_id, so it wins resolution", later > earlier);
  check("the same submission reproduces the same fact_id (idempotent replay, not a conflict)", idAt("2026-01-01T00:00:00Z"), earlier);
}

console.log("\nuntouched fields produce nothing at all");
{
  const { payload } = buildTrimEditBatch({
    ...TRIM_BASE, trim: { name: "Max", powertrain: "BEV" }, specEntries: [],
  });
  check("no spec entries means no APPEND_SPEC commands", payload.commands.length, 1);
  const trimPayload = (payload.commands[0] as any).payload.trims[0];
  ok("an untouched optional field is absent from the patch entirely", !("engine_cc" in trimPayload) && !("seats" in trimPayload));
}

console.log("\nexplicit clear vs untouched vs set (three states, never a silent zero)");
{
  const cleared = buildTrimEditBatch({
    ...TRIM_BASE, trim: { name: "Max", powertrain: "BEV", battery_kwh: null, notes: "" },
  }).payload.commands[0] as any;
  check("an explicit null clears an optional numeric field", cleared.payload.trims[0].battery_kwh, null);
  check("an explicit empty string clears an optional text field", cleared.payload.trims[0].notes, "");
  ok("cleared keys are present so dict.update() actually overwrites", "battery_kwh" in cleared.payload.trims[0] && "notes" in cleared.payload.trims[0]);

  const naSpec = buildTrimEditBatch({
    ...TRIM_BASE, trim: { name: "Max", powertrain: "BEV" },
    specEntries: [{ fieldKey: "engine.displacement_cc", labelForDiff: "Engine displacement (cc)", valueState: "NOT_APPLICABLE", value: 999 as any, unit: "cc" }],
  }).payload.commands[1] as any;
  check("NOT_APPLICABLE never carries a value even if one was passed", naSpec.payload.value, null);
  check("NOT_APPLICABLE never carries a unit", naSpec.payload.unit, "");
  check("NOT_APPLICABLE is recorded as its own state, not as zero", naSpec.payload.value_state, "NOT_APPLICABLE");
}

console.log("\nspec facts cannot attach to a trim that does not exist yet");
{
  let threw = false;
  try {
    buildTrimEditBatch({
      ...TRIM_BASE, existingTrimId: undefined,
      trim: { name: "Brand new", powertrain: "BEV" },
      specEntries: [{ fieldKey: "powertrain.max_power_kw", labelForDiff: "Maximum power (kW)", valueState: "KNOWN", value: 150, unit: "kW" }],
    });
  } catch { threw = true; }
  ok("creating a trim with spec facts in the same batch is refused (no id to attach to)", threw);

  const created = buildTrimEditBatch({
    ...TRIM_BASE, existingTrimId: undefined, trim: { name: "Brand new", powertrain: "BEV" }, specEntries: [],
  }).payload.commands[0] as any;
  ok("a new trim carries no canonical_id (the writer assigns identity)", !("canonical_id" in created.payload.trims[0]));
}

console.log("\nreason and evidence are optional, and the audit trail still reads");
{
  check("a blank reason becomes a plain statement instead of an empty string",
    composeReason({ sourceKind: "ADMIN", reviewedAt: "2026-01-01" }, ""), "Manual edit via Canonical Vehicle Editor");
  check("a blank reason still gets the evidence-kind prefix when one applies",
    composeReason(EVIDENCE, "   "), "[OEM evidence] Manual edit via Canonical Vehicle Editor");
  check("a written reason is kept", composeReason({ sourceKind: "ADMIN", reviewedAt: "2026-01-01" }, "fix torque"), "fix torque");
  const { payload } = buildTrimEditBatch({ ...TRIM_BASE, reason: "", evidence: { sourceKind: "ADMIN", reviewedAt: "2026-01-01" }, trim: { name: "Max", powertrain: "BEV" } });
  ok("a batch built with no reason and no evidence ref is still valid", payload.reason.length > 0 && payload.source.kind === "ADMIN" && payload.source.ref === undefined);
}

console.log("\none combined diff for the whole trim");
{
  const diff = diffTrimEdit({
    currentTrimFields: { seats: 5, tire_front: "215/55 R17" },
    trimPatch: { seats: 7, tire_front: "215/55 R17" },
    trimLabels: { seats: "Seats", tire_front: "Tire front" },
    currentSpecsByField: { "powertrain.max_power_kw": { value_state: "KNOWN", value: 120 } },
    specEntries: [{ fieldKey: "powertrain.max_power_kw", labelForDiff: "Maximum power (kW)", valueState: "KNOWN", value: 150, unit: "kW" }],
  });
  check("trim fields and spec facts appear in one diff list", diff.length, 3);
  ok("a real trim-field change is marked changed", diff.find((row: any) => row.field === "seats")!.changed);
  ok("a resubmitted identical trim field is not marked changed", !diff.find((row: any) => row.field === "tire_front")!.changed);
  ok("a spec fact change is marked changed", diff.find((row: any) => row.field === "powertrain.max_power_kw")!.changed);
}

console.log("\nduplicate MarketTrim identity detection never auto-merges");
{
  const existing = [
    { canonicalId: "t1", generationId: "gen1", name: "Max Plus", powertrain: "BEV" },
    { canonicalId: "t3", generationId: "gen2", name: "Max Plus", powertrain: "BEV" },
  ];
  check("same generation + powertrain + normalized name is flagged", findDuplicateMarketTrim(existing, { generationId: "gen1", name: "  MAX   plus ", powertrain: "bev" })?.canonicalId, "t1");
  ok("a different generation is not a duplicate", findDuplicateMarketTrim(existing, { generationId: "gen3", name: "Max Plus", powertrain: "BEV" }) === null);
  ok("a different powertrain is not a duplicate", findDuplicateMarketTrim(existing, { generationId: "gen1", name: "Max Plus", powertrain: "ICE" }) === null);
  ok("editing a trim against itself is not its own duplicate", findDuplicateMarketTrim(existing, { generationId: "gen1", name: "Max Plus", powertrain: "BEV", excludeCanonicalId: "t1" }) === null);
  check("normalizedTrimName folds case/spacing/punctuation", normalizedTrimName("  Max-Plus!! "), "max plus");
}

console.log("\nstructured source refs compile to MarketTrim.source_refs shape");
{
  const existing = { ecosticker: ["uuid-1"], official_site: ["https://oem.example/old"] };
  check("removing the only url under a kind drops that kind", applySourceRefEdits(existing, { remove: [{ kind: "official_site", url: "https://oem.example/old" }], add: [] }), { ecosticker: ["uuid-1"] });
  check("re-adding an existing pair does not duplicate", applySourceRefEdits(existing, { remove: [], add: [{ kind: "ecosticker", url: "uuid-1" }] }).ecosticker, ["uuid-1"]);
  check("remove and add can target the same kind", applySourceRefEdits(existing, { remove: [{ kind: "ecosticker", url: "uuid-1" }], add: [{ kind: "ecosticker", url: "uuid-2" }] }).ecosticker, ["uuid-2"]);
}

console.log("\nstale-edit protection");
{
  ok("same release_id is not stale", !isStaleRelease("rel-1", "rel-1"));
  ok("a different release_id is stale", isStaleRelease("rel-1", "rel-2"));
  ok("a missing page fingerprint never blocks", !isStaleRelease("", "rel-2"));
}

console.log("\ndiffPatch — only touched fields appear");
{
  const rows = diffPatch({ name_en: "Old", body_type: "SEDAN" }, { name_en: "New" }, { name_en: "Name" });
  check("only the touched key produces a diff row", rows.length, 1);
  ok("the touched row is marked changed", rows[0].changed);
}
{
  const { payload } = buildModelGenerationBatch({
    batchId: "b-model", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "fix taxonomy",
    evidence: { sourceKind: "ADMIN", reviewedAt: "2026-01-01" }, canonicalModelId: "toyota.yaris_ativ",
    brand: { id: "toyota", nameEn: "Toyota" }, generationCode: "MXPA10",
    modelPatch: { name_en: "Yaris Ativ" }, generationPatch: {},
  });
  const command = payload.commands[0] as any;
  check("model edits keep the caller's stable canonical_id", command.canonical_id, "toyota.yaris_ativ");
  check("generation code is re-submitted unchanged to preserve identity", command.payload.generation.code, "MXPA10");
  ok("untouched model fields stay out of the patch", !("body_type" in command.payload.model));
}

console.log("\nsource-text regression — one trim editor, no draft machinery left");
{
  const actions = fs.readFileSync("app/admin/vehicle-editor-actions.ts", "utf8");
  for (const fn of ["prepareModelGenerationEdit", "prepareTrimEdit", "confirmEditProposal"]) {
    ok(`${fn} is admin-gated`, new RegExp(`export async function ${fn}[\\s\\S]{0,200}isAdmin\\(\\)`).test(actions));
  }
  for (const gone of ["addSpecDraftEntry", "removeSpecDraftEntry", "discardSpecDraft", "prepareSpecDraftReview", "prepareMarketTrimEdit"]) {
    ok(`${gone} (old multi-step spec flow) is gone`, !actions.includes(gone));
  }
  ok("trim fields and spec facts are compiled by the one unified builder", /buildTrimEditBatch\(/.test(actions));
  ok("spec facts are read straight off the same trim form (spec__<key>)", /spec__\$\{definition\.key\}/.test(actions));
  ok("an explicit NA checkbox records NOT_APPLICABLE rather than a zero", /spec_na__\$\{definition\.key\}[\s\S]{0,600}NOT_APPLICABLE/.test(actions));
  ok("a spec value identical to the stored one is skipped (no no-op command)", /JSON\.stringify\(currentFact\?\.value\) === JSON\.stringify\(parsed\)\) continue/.test(actions));
  ok("a trim field identical to the stored one is skipped", /if \(value !== Number\(currentValue\)\)/.test(actions) && /if \(!raw \|\| raw === currentValue\) return;/.test(actions));
  ok("an edit that changes nothing is refused instead of queueing an empty batch", /ไม่มีอะไรเปลี่ยน/.test(actions));
}

console.log("\nsource-text regression — reason and evidence are no longer mandatory anywhere");
{
  const actions = fs.readFileSync("app/admin/vehicle-editor-actions.ts", "utf8");
  ok("no form requires a reason", !/requiredField\(formData, "reason"/.test(actions));
  ok("no form requires an evidence ref", !/requireRef/.test(actions));
  ok("evidence refs are free text, not URL-validated (a brochure name is fine)", !/evidenceUrl/.test(actions));
  ok("evidence kind falls back to ADMIN instead of rejecting a blank", /EVIDENCE_KINDS\.has\(rawKind\) \? rawKind : "ADMIN"/.test(actions));
  ok("review date defaults to today instead of being required", /\|\| new Date\(\)\.toISOString\(\)\.slice\(0, 10\)/.test(actions));
  const form = fs.readFileSync("app/admin/(secure)/vehicles/[modelId]/page.tsx", "utf8");
  ok("the reason input is marked optional in the UI, not required", /name="reason"[^>]*placeholder="เว้นว่างได้"/.test(form) && !/name="reason"[^>]*required/.test(form));
  ok("the evidence ref input is not required in the UI", !/name="evidence_ref"[^>]*required/.test(form));
}

console.log("\nsource-text regression — confirm stays retry-safe and ownership-scoped");
{
  const actions = fs.readFileSync("app/admin/vehicle-editor-actions.ts", "utf8");
  ok("confirm loads (not consumes) before enqueueing so a transient failure is retryable",
    /const proposal = await loadProposal\(proposalId, editor\.name\)[\s\S]{0,700}await enqueueCanonicalInputBatch\(proposal\.batchPayload/.test(actions));
  ok("confirm consumes only after a successful enqueue",
    /await enqueueCanonicalInputBatch\(proposal\.batchPayload[\s\S]{0,300}await consumeProposal\(proposalId, editor\.name\)/.test(actions));
  ok("every prepare action checks the release fingerprint", (actions.match(/assertNotStale\(/g) || []).length >= 3);
  ok("the only write path is enqueueCanonicalInputBatch", !/adminDb\(\)/.test(actions));
  ok("nothing targets current_vehicle_ / canonical_ tables directly", !/\.from\(["'`](current_|canonical_)/.test(actions));

  const store = fs.readFileSync("lib/edit-session-store.ts", "utf8");
  ok("proposal ids are high-entropy random tokens", /randomBytes\(24\)/.test(store));
  ok("every load/consume is scoped by actor in the query itself", (store.match(/\.eq\("actor", actor\)/g) || []).length >= 2);
  ok("consume is one atomic conditional UPDATE", /status: "CONSUMED"[\s\S]{0,300}eq\("status", "PENDING_REVIEW"\)/.test(store));
  ok("the DRAFT status machinery is gone", !/DRAFT/.test(store));
}

console.log("\nsource-text regression — the trim editor shows everything in one flat form");
{
  const page = fs.readFileSync("app/admin/(secure)/vehicles/[modelId]/page.tsx", "utf8");
  ok("there is one trim editor form, not a pick-one-field-at-a-time dropdown", /action={prepareTrimEdit}/.test(page) && !/เลือก spec field/.test(page));
  ok("spec fields are rendered from the registry into human categories", /CATEGORY_OF_GROUP/.test(page) && /specsByCategory/.test(page));
  ok("all four categories exist, including safety/ADAS", /Powertrain & Performance/.test(page) && /Body, Chassis & Wheels/.test(page) && /Safety, ADAS & Comfort/.test(page) && /Other/.test(page));
  ok("safety/ADAS fields are shown in full, not hidden behind a 'show more'", /specs\.map\(\(definition\) => <SpecField/.test(page));
  ok("category sections start open so the whole trim is visible at once", /className="adminFieldWide adminNotice" open>/.test(page));
  ok("the old separate specs-per-trim section is gone", !/Specs ต่อ MarketTrim/.test(page) && !/prepareSpecDraftReview/.test(page));
  ok("trim editing still links out to Price Bench rather than duplicating it", /vehicle-input\?model=/.test(page));
  ok("the queue banner explains that a merge is needed before data goes live", /PR ถูก merge/.test(page));
  ok("generation code is never an editable input (identity-preserving)", !/name="code"/.test(page) && !/name="generation_code"/.test(page));
}

console.log("\nsource-text regression — the bugs found in the UI review are fixed");
{
  ok("an admin error boundary exists so a thrown guard is not a raw crash screen", fs.existsSync("app/admin/error.tsx"));
  ok("a boundary also sits inside (secure) so a failed edit keeps the admin shell and nav", fs.existsSync("app/admin/(secure)/error.tsx"));
  for (const file of ["app/admin/error.tsx", "app/admin/(secure)/error.tsx"]) {
    ok(`${file} is a client component`, fs.readFileSync(file, "utf8").startsWith('"use client"'));
  }
  const panel = fs.readFileSync("components/admin/AdminErrorPanel.tsx", "utf8");
  ok("both boundaries share one panel instead of duplicating the markup", /export function AdminErrorPanel/.test(panel));
  ok("the panel shows the thrown message and offers a retry", /error\.message/.test(panel) && /reset/.test(panel));
  ok("the panel states that nothing was written, so a guard does not read as data loss", /ยังไม่ถูกบันทึก/.test(panel));

  const css = fs.readFileSync("app/globals.css", "utf8");
  ok(".adminClearToggle is styled (was used but undefined)", /\.adminClearToggle\{/.test(css));
  ok(".adminHint is styled (was used but undefined)", /\.adminHint\{/.test(css));

  const home = fs.readFileSync("app/admin/(secure)/page.tsx", "utf8");
  ok("/admin reads ?canonical=1 instead of silently dropping it", /searchParams/.test(home) && /canonical \?/.test(home));
}

console.log("\nsource-text regression — canonical-editor.ts stays read-only");
{
  const editor = fs.readFileSync("lib/canonical-editor.ts", "utf8");
  ok("only selects from serving projections, never writes", !/\.(update|insert|upsert|delete)\(/.test(editor));
  ok("reads the trim + spec projections", /current_market_trims/.test(editor) && /current_spec_facts/.test(editor));
  const builder = fs.readFileSync("lib/canonical-command-builder.ts", "utf8");
  ok("MarketTrimFields never carries a price (price stays with the Price Ledger)", !/price_thb|amount_thb/.test(builder));
  ok("no '@/' alias imports (keeps the builder executable outside the bundler)", !/from "@\//.test(builder));
}

console.log("\nsource-text regression — migration stays locked down and unapplied");
{
  const migration = fs.readFileSync("supabase/migration_v35_admin_edit_sessions.sql", "utf8");
  ok("RLS is enabled", /enable row level security/.test(migration));
  ok("public/anon/authenticated are revoked", /revoke all on table public\.admin_edit_sessions from public, anon, authenticated/.test(migration));
  ok("only service_role is granted", /to service_role;/.test(migration));
  ok("no anon/authenticated grant anywhere", !/grant[^;]*to (anon|authenticated)/.test(migration));
}

console.log("\nbackward compatibility — existing admin benches untouched");
{
  ok("/admin/vehicle-input Advanced JSON still present", /enqueueVehicleInput/.test(fs.readFileSync("app/admin/(secure)/vehicle-input/page.tsx", "utf8")));
  for (const file of [
    "app/admin/input-actions.ts", "app/admin/eco-trim-actions.ts", "app/admin/price-actions.ts",
    "app/admin/retail-lifecycle-actions.ts", "app/admin/trim-retail-lifecycle-actions.ts",
  ]) {
    ok(`${file} still exports its original server actions`, fs.readFileSync(file, "utf8").startsWith('"use server"'));
  }
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall Canonical Vehicle Editor checks passed");
process.exit(failed ? 1 : 0);
