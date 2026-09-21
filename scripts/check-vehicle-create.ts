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

const { buildNewVehicleBatch } = await import("../lib/canonical-vehicle-create.ts");

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

const fixtureDir = path.join("automotive", "vehicle_master", "tests", "fixtures");
fs.mkdirSync(fixtureDir, { recursive: true });
fs.writeFileSync(path.join(fixtureDir, "admin_create_existing_brand.json"),
  JSON.stringify(existingBrand.payload, null, 2) + "\n");
fs.writeFileSync(path.join(fixtureDir, "admin_create_new_brand.json"),
  JSON.stringify(newBrand.payload, null, 2) + "\n");
console.log("  wrote fixtures for tests/test_admin_create_vehicle.py");

if (failed) {
  console.log(`\n${failed} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");
