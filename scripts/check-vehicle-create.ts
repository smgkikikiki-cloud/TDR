// Same convention as the rest of scripts/check-*.ts: lib/canonical-vehicle-create.ts
// carries zero "@/" alias imports, so this script loads and *executes* it and
// asserts on real return values -- not a source-grep. The batches this
// produces are then written to automotive/vehicle_master/tests/fixtures/ so a
// real Python test can feed the EXACT same payload through
// CanonicalInputPipeline.apply() and prove it is accepted and produces the
// right catalogue (Tests A and B of the FINAL FUNCTIONAL BLOCKER PASS): this
// script never claims that on its own, since it never touches the real
// canonical write pipeline.
import fs from "node:fs";
import path from "node:path";

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

const { buildNewVehicleBatch, trimIsRequired, resolveTrimInput, classifyCreatedVehicleStatus } =
  await import("../lib/canonical-vehicle-create.ts");
const POWERTRAINS = ["ICE", "HEV", "PHEV", "REEV", "BEV", "FCEV"] as const;

console.log("TEST — existing brand, new model+trim (Test A shape)");
const existingBrand = buildNewVehicleBatch({
  batchId: "check-existing-brand-1", year: 2026, submittedAt: "2026-09-21T00:00:00+00:00",
  reason: "", actor: "check-script",
  brand: { mode: "existing", id: "toyota" },
  model: { nameEn: "Test Model X" },
  generationCode: "X1",
  trim: { name: "Premium", powertrain: "hev" },
});
{
  const command = existingBrand.payload.commands[0] as any;
  check("operation", command.operation, "UPSERT_MODEL_BUNDLE");
  ok("no canonical_id typed by caller", command.canonical_id === undefined);
  check("brand patch is id-only for an existing brand", command.payload.brand, { id: "toyota" });
  check("model patch", command.payload.model, { name_en: "Test Model X", incomplete: true });
  check("generation patch", command.payload.generation, { code: "X1" });
  check("variants empty -- no fabricated spec", command.payload.variants, []);
  check("trim powertrain uppercased", command.payload.trims, [{ name: "Premium", powertrain: "HEV" }]);
  check("source.kind is ADMIN", existingBrand.payload.source, { kind: "ADMIN" });
}

console.log("TEST — new brand + new model (Test B shape)");
const newBrand = buildNewVehicleBatch({
  batchId: "check-new-brand-1", year: 2026, submittedAt: "2026-09-21T00:00:00+00:00",
  reason: "", actor: "check-script",
  brand: { mode: "new", nameEn: "Test New Brand" },
  model: { nameEn: "Model One" },
  generationCode: "GEN1",
  trim: { name: "Standard", powertrain: "ice" },
});
{
  const command = newBrand.payload.commands[0] as any;
  ok("no canonical_id typed by caller", command.canonical_id === undefined);
  check("brand patch carries only what the admin typed -- no id minted here", command.payload.brand,
    { name_en: "Test New Brand" });
  check("model.incomplete true -- no fabricated body_type/variants", command.payload.model.incomplete, true);
}

console.log("TEST — a second identical submission is the same batch_id (queue-level dedupe)");
const resubmit = buildNewVehicleBatch({
  batchId: "check-existing-brand-1", year: 2026, submittedAt: "2026-09-21T00:00:00+00:00",
  reason: "", actor: "check-script",
  brand: { mode: "existing", id: "toyota" },
  model: { nameEn: "Test Model X" },
  generationCode: "X1",
  trim: { name: "Premium", powertrain: "hev" },
});
check("identical inputs produce an identical payload",
  JSON.stringify(resubmit.payload), JSON.stringify(existingBrand.payload));

console.log("TEST — existing brand, MODEL-grain: no trim at all (Test 1A shape)");
const modelOnlyExisting = buildNewVehicleBatch({
  batchId: "check-model-only-existing-1", year: 2026, submittedAt: "2026-09-21T00:00:00+00:00",
  reason: "", actor: "check-script",
  brand: { mode: "existing", id: "toyota" },
  model: { nameEn: "Test Model Y" },
  generationCode: "Y1",
  // trim deliberately omitted -- a MODEL-grain DLT row never names one.
});
{
  const command = modelOnlyExisting.payload.commands[0] as any;
  ok("no canonical_id typed by caller", command.canonical_id === undefined);
  check("brand patch is id-only for an existing brand", command.payload.brand, { id: "toyota" });
  check("model patch", command.payload.model, { name_en: "Test Model Y", incomplete: true });
  check("generation patch", command.payload.generation, { code: "Y1" });
  check("variants empty -- no fabricated spec", command.payload.variants, []);
  check("trims empty -- no fabricated grade/powertrain", command.payload.trims, []);
}

console.log("TEST — new brand, MODEL-grain: no trim at all (Test 1B shape)");
const modelOnlyNewBrand = buildNewVehicleBatch({
  batchId: "check-model-only-new-brand-1", year: 2026, submittedAt: "2026-09-21T00:00:00+00:00",
  reason: "", actor: "check-script",
  brand: { mode: "new", nameEn: "Test Model Only Brand" },
  model: { nameEn: "Model Two" },
  generationCode: "GEN1",
});
{
  const command = modelOnlyNewBrand.payload.commands[0] as any;
  check("brand patch carries only what the admin typed -- no id minted here", command.payload.brand,
    { name_en: "Test Model Only Brand" });
  check("model.incomplete true", command.payload.model.incomplete, true);
  check("trims empty", command.payload.trims, []);
}

console.log("TEST — trimIsRequired: the exact decision app/admin/vehicle-create-actions.ts's readTrim makes");
check("TRIM grain always requires a trim", trimIsRequired("TRIM", null), true);
check("TRIM grain requires a trim even if create_mode says model_only",
  trimIsRequired("TRIM", "model_only"), true);
check("MODEL grain never offers a trim", trimIsRequired("MODEL", null), false);
check("MODEL grain never offers a trim even if create_mode says with_trim",
  trimIsRequired("MODEL", "with_trim"), false);
check("no grain (direct create) defaults to model-only", trimIsRequired(null, null), false);
check("no grain (direct create), explicit with_trim", trimIsRequired(null, "with_trim"), true);

console.log("TEST 1C — grain=TRIM with no trim/powertrain is refused with a clear error");
{
  let threw = false;
  try {
    resolveTrimInput({
      required: trimIsRequired("TRIM", null),
      name: "", powertrain: "", allowedPowertrains: POWERTRAINS,
    });
  } catch (error) {
    threw = true;
    ok("error message is the Thai 'ใส่ชื่อรุ่นย่อย' prompt, not a stack trace",
      error instanceof Error && error.message === "กรุณาใส่ชื่อรุ่นย่อย");
  }
  ok("resolveTrimInput throws rather than silently building an UNKNOWN-powertrain trim", threw);
}
{
  // Name given, powertrain still missing -- must still refuse (MarketTrim
  // cannot validate with UNKNOWN powertrain either way).
  let threw = false;
  try {
    resolveTrimInput({
      required: true, name: "Premium", powertrain: "", allowedPowertrains: POWERTRAINS,
    });
  } catch (error) {
    threw = true;
    ok("missing powertrain alone is also refused", error instanceof Error
      && error.message === "กรุณาเลือก powertrain");
  }
  ok("threw", threw);
}

console.log("TEST 1D — grain=TRIM with trim+powertrain given creates it correctly");
{
  const trim = resolveTrimInput({
    required: trimIsRequired("TRIM", null),
    name: "Premium", powertrain: "hev", allowedPowertrains: POWERTRAINS,
  });
  check("resolved trim", trim, { name: "Premium", powertrain: "HEV" });
  const batch = buildNewVehicleBatch({
    batchId: "check-trim-grain-1", year: 2026, submittedAt: "2026-09-21T00:00:00+00:00",
    reason: "", actor: "check-script",
    brand: { mode: "existing", id: "toyota" },
    model: { nameEn: "Test Model Z" },
    generationCode: "Z1",
    trim,
  });
  const command = batch.payload.commands[0] as any;
  check("trim lands in the command", command.payload.trims, [{ name: "Premium", powertrain: "HEV" }]);
}

console.log("TEST — classifyCreatedVehicleStatus: acceptance cases A-F (Fix 3)");
// A. QUEUED, target=null -> pending
check("A: QUEUED/null is pending", classifyCreatedVehicleStatus({
  status: "QUEUED", error: null, target: null,
}).kind, "pending");
// B. PROCESSING, target=null -> pending
check("B: PROCESSING/null is pending", classifyCreatedVehicleStatus({
  status: "PROCESSING", error: null, target: null,
}).kind, "pending");
// C. STAGED, target=null -> pending
check("C: STAGED/null is pending", classifyCreatedVehicleStatus({
  status: "STAGED", error: null, target: null,
}).kind, "pending");
// D. FAILED with an error, target=null -> FAILED UI, error visible, never pending
{
  const result = classifyCreatedVehicleStatus({
    status: "FAILED", error: "duplicate canonical id", target: null,
  });
  check("D: FAILED is classified failed, not pending", result.kind, "failed");
  check("D: FAILED error message is carried through", result.error, "duplicate canonical id");
  check("D: FAILED never carries a target to preselect", result.target, null);
  ok("D: FAILED is never the same kind as a genuinely pending batch",
    result.kind !== classifyCreatedVehicleStatus({ status: "QUEUED", error: null, target: null }).kind);
}
// Also cover the two other terminal, human-must-act statuses the same
// column allows (migration_v22's check constraint) -- neither is pending.
check("NEEDS_REVIEW is classified failed, not pending", classifyCreatedVehicleStatus({
  status: "NEEDS_REVIEW", error: null, target: null,
}).kind, "failed");
check("REJECTED is classified failed, not pending", classifyCreatedVehicleStatus({
  status: "REJECTED", error: null, target: null,
}).kind, "failed");
// E. PUBLISHED, target exists -> ready, target preselected
{
  const result = classifyCreatedVehicleStatus({
    status: "PUBLISHED", error: null, target: "toyota.test_model_x",
  });
  check("E: PUBLISHED+target is ready", result.kind, "ready");
  check("E: target is carried through for preselection", result.target, "toyota.test_model_x");
}
// F. PUBLISHED, target missing -> explicit readback error, NOT "กำลังสร้าง" (pending)
{
  const result = classifyCreatedVehicleStatus({ status: "PUBLISHED", error: null, target: null });
  check("F: PUBLISHED with no target is readback_error", result.kind, "readback_error");
  ok("F: readback_error is never classified as pending",
    result.kind !== "pending");
}

const fixtureDir = path.join("automotive", "vehicle_master", "tests", "fixtures");
fs.mkdirSync(fixtureDir, { recursive: true });
fs.writeFileSync(path.join(fixtureDir, "admin_create_existing_brand.json"),
  JSON.stringify(existingBrand.payload, null, 2) + "\n");
fs.writeFileSync(path.join(fixtureDir, "admin_create_new_brand.json"),
  JSON.stringify(newBrand.payload, null, 2) + "\n");
fs.writeFileSync(path.join(fixtureDir, "admin_create_model_only_existing_brand.json"),
  JSON.stringify(modelOnlyExisting.payload, null, 2) + "\n");
fs.writeFileSync(path.join(fixtureDir, "admin_create_model_only_new_brand.json"),
  JSON.stringify(modelOnlyNewBrand.payload, null, 2) + "\n");
console.log("  wrote fixtures for tests/test_admin_create_vehicle.py");

if (failed) {
  console.log(`\n${failed} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");
