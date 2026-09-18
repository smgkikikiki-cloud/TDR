// The trim editor's core promise, tested against real canonical data:
// one field per concept, one form, one diff, one batch — and whatever the
// backend splits that into stays behind the adapter.
//
// Same convention as the rest of scripts/check-*.ts: lib/trim-editor-fields.ts,
// lib/trim-editor-state.ts, lib/spec-field-registry.ts and
// lib/canonical-command-builder.ts carry zero "@/" alias imports, so this
// script loads and *executes* them and asserts on real return values. The
// AION ES fixture is generated from the canonical tree by
// scripts/build-aion-es-fixture.py, so it is the production payload shape and
// not somebody's idea of it.
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
  resolveTrimEditorFields, fieldAppliesTo, fieldsByCategory, validateFieldValue,
  validateTrimConsistency, UNSURFACED_SPEC_KEYS, TRIM_CATEGORIES,
} = await import("../lib/trim-editor-fields.ts");
const { loadSpecFieldRegistry } = await import("../lib/spec-field-registry.ts");
const {
  normalizeTrimForEditor, marketTrimFieldsFromPayload, resolvedSpecsFromPayload,
  trimLocalId,
} = await import("../lib/trim-editor-state.ts");
const {
  buildTrimEditBatch, diffTrimEdit, describeValue, composeReason,
  findDuplicateMarketTrim, isStaleRelease, applySourceRefEdits, normalizedTrimName,
} = await import("../lib/canonical-command-builder.ts");

const REGISTRY = loadSpecFieldRegistry(2026);
const FIELDS = resolveTrimEditorFields(REGISTRY);
const byKey = (key: string) => FIELDS.find((f) => f.key === key)!;

const FIXTURE = JSON.parse(fs.readFileSync("tests/fixtures/aion-es-market-trims.json", "utf8"));
const COMFORT = FIXTURE.market_trims.find((row: any) => row.name === "Comfort / Private Use");
const EVIDENCE = { sourceKind: "OEM" as const, sourceRef: "https://oem.example/spec", reviewedAt: "2026-01-01" };

// =====================================================================
console.log("TEST 1 — one UI field fans out to every backend that stores the concept");
// =====================================================================
{
  // The eleven pairs that used to render as two boxes each, plus powertrain.
  // This is the whole point of lib/trim-editor-fields.ts, so it is asserted
  // exhaustively rather than by sampling.
  const expected: Array<[string, string, string]> = [
    ["powertrain", "powertrain", "identity.powertrain"],
    ["drivetrain", "drivetrain", "powertrain.drivetrain"],
    ["engine_cc", "engine_cc", "engine.displacement_cc"],
    ["transmission", "transmission", "powertrain.transmission"],
    ["battery_kwh", "battery_kwh", "battery.catalog_capacity_kwh"],
    ["seats", "seats", "vehicle.seats"],
    ["length_mm", "length_mm", "vehicle.length_mm"],
    ["width_mm", "width_mm", "vehicle.width_mm"],
    ["height_mm", "height_mm", "vehicle.height_mm"],
    ["wheelbase_mm", "wheelbase_mm", "vehicle.wheelbase_mm"],
    ["tire_front", "tire_front", "fitment.tyre_front"],
    ["tire_rear", "tire_rear", "fitment.tyre_rear"],
  ];
  for (const [uiKey, trimField, specKey] of expected) {
    const field = FIELDS.find((f) => f.key === uiKey);
    check(`${uiKey} maps to MarketTrim.${trimField} + ${specKey}`,
      field ? [field.targets.trimField, field.targets.specKey] : null, [trimField, specKey]);
  }

  const uiKeys = FIELDS.map((f) => f.key);
  check("no UI field key appears twice", uiKeys.filter((k, i) => uiKeys.indexOf(k) !== i), []);
  const specKeys = FIELDS.map((f) => f.targets.specKey).filter(Boolean);
  check("no comparable-spec key is rendered by two fields",
    specKeys.filter((k, i) => specKeys.indexOf(k) !== i), []);

  // Every registry field is either rendered exactly once or explicitly
  // unsurfaced with a reason. Nothing is silently dropped.
  const surfaced = new Set(specKeys);
  const missing = REGISTRY.map((d) => d.key)
    .filter((key) => !surfaced.has(key) && !UNSURFACED_SPEC_KEYS.includes(key));
  check("every registry field is rendered or explicitly unsurfaced", missing, []);
  ok("the unsurfaced list is short and deliberate", UNSURFACED_SPEC_KEYS.length === 2);

  check("every category in the catalog is one the editor renders",
    FIELDS.filter((f) => !TRIM_CATEGORIES.some((c) => c.id === f.category)).map((f) => f.key), []);
}

// =====================================================================
console.log("\nACCEPTANCE — opening AION ES Comfort shows exactly one box per concept");
// =====================================================================
{
  ok("the fixture carries both AION ES trims", FIXTURE.market_trims.length === 2
    && FIXTURE.market_trims.some((r: any) => r.name === "Standard (Fleet / Taxi EV)"));

  const shown = FIELDS
    .filter((f) => !f.identityLocked && fieldAppliesTo(f, "BEV"))
    .map((f) => f.labelEn);
  for (const label of [
    "Drivetrain", "Motor type", "Max power", "Max torque", "Battery capacity",
    "Battery chemistry", "Battery manufacturer / supplier", "Rated driving range",
    "Seats", "Length", "Width", "Height", "Wheelbase", "Front tyre", "Rear tyre",
    "Tyre size", "Charging connector", "Excise tax rate", "Emissions standard",
  ]) {
    check(`exactly one "${label}" box`, shown.filter((l) => l === label).length, 1);
  }
  check("no label is rendered twice anywhere in the BEV form",
    shown.filter((l, i) => shown.indexOf(l) !== i), []);

  // The trap the user named: a BEV must not be asked for engine displacement.
  ok("a BEV form offers no engine displacement box", !shown.includes("Engine displacement"));
  ok("a BEV form offers no engine code box", !shown.includes("Engine code"));
  ok("a BEV form offers no fuel type or combustion type box",
    !shown.includes("Fuel type") && !shown.includes("Combustion type"));

  const ice = FIELDS.filter((f) => fieldAppliesTo(f, "ICE")).map((f) => f.key);
  ok("an ICE form does offer engine displacement", ice.includes("engine_cc"));
  // The fuel a car takes (E20/E85/B20) is what a Thai buyer filters on, and
  // combustion_type is the only field that can tell a hybrid from a plain
  // engine, because the ECO export files both as "ICE".
  ok("an ICE form offers fuel type and combustion type",
    ice.includes("fuel_type") && ice.includes("combustion_type"));
  ok("an ICE form offers combined fuel consumption", ice.includes("fuel_consumption"));
  ok("a BEV form does not ask for fuel consumption",
    !FIELDS.filter((f) => fieldAppliesTo(f, "BEV")).some((f) => f.key === "fuel_consumption"));

  // Test cycle is a qualifier of range, rendered beside it — not a field of
  // its own and not something that can go missing.
  check("Rated driving range carries the test-cycle qualifier",
    byKey("rated_range_km").qualifiers.map((q) => q.key), ["measurement_basis", "range_scope"]);
  ok("the test-cycle qualifier offers NEDC",
    byKey("rated_range_km").qualifiers[0].options!.includes("NEDC"));
  check("NCAP carries all four registry qualifiers",
    byKey("safety_ncap_stars").qualifiers.map((q) => q.key),
    ["program", "protocol", "tested_variant", "market"]);
  check("DC charging time carries its SoC window and charger power",
    byKey("charging_dc_time_min").qualifiers.map((q) => q.key),
    ["soc_from", "soc_to", "charger_power_kw"]);
  ok("a plain field carries no qualifier controls at all",
    byKey("seats").qualifiers.length === 0 && byKey("width_mm").qualifiers.length === 0);

  const groups = fieldsByCategory(FIELDS.filter((f) => fieldAppliesTo(f, "BEV")));
  ok("the form is grouped into the categories a person reads in order",
    groups.length >= 7 && groups[0].category.id === "identity");
  ok("safety and ADAS are one group, not two",
    groups.filter((g) => g.category.id === "safety").length === 1
    && groups.find((g) => g.category.id === "safety")!.fields.length >= 7);
}

// =====================================================================
console.log("\nTEST 9 — Battery manufacturer is battery.supplier, not a new field");
// =====================================================================
{
  const field = byKey("battery_supplier");
  check("Battery manufacturer writes to the existing battery.supplier key",
    field.targets.specKey, "battery.supplier");
  ok("it creates no MarketTrim column of its own", field.targets.trimField === undefined);
  ok("it is labelled as the manufacturer/supplier",
    /Battery manufacturer/.test(field.labelEn) && /supplier/i.test(field.labelEn));

  const order = FIELDS.map((f) => f.key);
  check("it sits immediately after battery chemistry",
    order[order.indexOf("battery_chemistry") + 1], "battery_supplier");
  ok("it applies to every battery powertrain the registry allows",
    field.powertrains.join(",") === "HEV,PHEV,REEV,BEV");
}

// =====================================================================
console.log("\nTEST 2 — the production payload.specs shape is read, not guessed");
// =====================================================================
{
  const payload = COMFORT.payload;
  ok("the production row really does nest MarketTrim columns under payload.specs",
    typeof payload.specs === "object" && "drivetrain" in payload.specs);
  ok("and really does NOT carry them at the payload root",
    !("drivetrain" in payload) && !("seats" in payload));

  const flat = marketTrimFieldsFromPayload(payload);
  check("normalization reads them from payload.specs", flat.id, COMFORT.canonical_id);
  check("a legacy/flat row still opens instead of rendering blank",
    marketTrimFieldsFromPayload({ drivetrain: "FWD", seats: 5 }).seats, 5);
  check("a payload with specs never merges stray root keys",
    marketTrimFieldsFromPayload({ specs: { seats: 5 }, seats: 99 }).seats, 5);
  check("a junk payload normalizes to empty rather than throwing",
    marketTrimFieldsFromPayload(null), {});

  const normalized = normalizeTrimForEditor({
    payload, fields: FIELDS, canonicalId: COMFORT.canonical_id,
    generationId: COMFORT.generation_id, name: COMFORT.name, powertrain: COMFORT.powertrain,
  });
  check("identity comes back intact", normalized.canonicalId, COMFORT.canonical_id);
  ok("every applicable field gets an entry, so no box renders undefined",
    FIELDS.filter((f) => fieldAppliesTo(f, "BEV")).every((f) => Boolean(normalized.editableSpecs[f.key])));
  check("AION ES Comfort's drivetrain really is unset today",
    normalized.editableSpecs.drivetrain, { value: "", valueState: "UNKNOWN", qualifiers: {}, origin: "none" });
  check("the trim's name prefills", normalized.editableSpecs.name.value, "Comfort / Private Use");
  check("its real source_refs survive normalization",
    normalized.sourceRefs, { owner_directory: ["owner_directory_2026_09_13:001"] });

  // "UNKNOWN" is the drivetrain column's empty value, not something an admin
  // typed; showing it in the box would be a lie about what is recorded.
  check("a drivetrain stored as UNKNOWN reads as empty, not as the word UNKNOWN",
    normalizeTrimForEditor({
      payload: { specs: { drivetrain: "UNKNOWN" } }, fields: FIELDS, powertrain: "BEV",
    }).editableSpecs.drivetrain.value, "");

  check("trimLocalId recovers the writer's identity segment",
    trimLocalId(COMFORT.canonical_id), "comfort_private_use_bev");
  check("trimLocalId on a trim that does not exist yet is empty", trimLocalId(""), "");
}

// =====================================================================
console.log("\nTEST 8 — a value stored in two backends is read back as one box");
// =====================================================================
{
  // MarketTrim column populated, no fact yet: the single box shows the column.
  const fromColumn = normalizeTrimForEditor({
    payload: { specs: { seats: 5, drivetrain: "FWD", battery_kwh: 55.2 } },
    fields: FIELDS, powertrain: "BEV",
  }).editableSpecs;
  check("Seats reads back from the MarketTrim column", fromColumn.seats.value, "5");
  check("and is marked as having come from the trim row", fromColumn.seats.origin, "trim");
  check("Drivetrain reads back from the MarketTrim column", fromColumn.drivetrain.value, "FWD");
  check("Battery capacity reads back from the MarketTrim column", fromColumn.battery_kwh.value, "55.2");

  // A spec fact exists too: it wins, because only it carries state and
  // qualifiers. One box either way.
  const fromFact = normalizeTrimForEditor({
    payload: {
      specs: { seats: 5 },
      comparable_specs: [{ field_key: "vehicle.seats", value_state: "KNOWN", value: 7, unit: "seat" }],
    },
    fields: FIELDS, powertrain: "BEV",
  }).editableSpecs;
  check("when both backends hold the concept, the fact is authoritative", fromFact.seats.value, "7");
  check("and the origin says so", fromFact.seats.origin, "spec");

  // And on the way out, one box writes to both.
  const { payload } = buildTrimEditBatch({
    batchId: "b1", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "",
    evidence: EVIDENCE, canonicalModelId: "aion.aion_es",
    brand: { id: "aion", nameEn: "Aion" }, generationCode: "aes",
    generationId: "aion.aion_es.aes", existingTrimId: COMFORT.canonical_id,
    identity: { name: "Comfort / Private Use", powertrain: "BEV" },
    fields: FIELDS,
    submissions: [
      { key: "seats", valueState: "KNOWN", value: 5, qualifiers: {} },
      { key: "drivetrain", valueState: "KNOWN", value: "FWD", qualifiers: {} },
      { key: "battery_kwh", valueState: "KNOWN", value: 55.2, qualifiers: {} },
    ],
  });
  const [bundle, ...specs] = payload.commands as any[];
  const trimRow = bundle.payload.trims[0];
  check("Seats lands in the MarketTrim column", trimRow.seats, 5);
  check("Drivetrain lands in the MarketTrim column", trimRow.drivetrain, "FWD");
  check("Battery capacity lands in the MarketTrim column", trimRow.battery_kwh, 55.2);
  check("and the same three values also land as comparable-spec facts",
    specs.map((c: any) => [c.payload.field_key, c.payload.value]),
    [["vehicle.seats", 5], ["powertrain.drivetrain", "FWD"], ["battery.catalog_capacity_kwh", 55.2]]);
  ok("the admin submitted each of them exactly once",
    new Set(specs.map((c: any) => c.payload.field_key)).size === 3);
}

// =====================================================================
console.log("\nTEST 6 — a range of 442 km keeps its NEDC, end to end");
// =====================================================================
{
  const { payload } = buildTrimEditBatch({
    batchId: "b2", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "",
    evidence: EVIDENCE, canonicalModelId: "aion.aion_es",
    brand: { id: "aion", nameEn: "Aion" }, generationCode: "aes",
    generationId: "aion.aion_es.aes", existingTrimId: COMFORT.canonical_id,
    identity: { name: "Comfort / Private Use", powertrain: "BEV" },
    fields: FIELDS,
    submissions: [{
      key: "rated_range_km", valueState: "KNOWN", value: 442,
      qualifiers: { measurement_basis: "NEDC" },
    }],
  });
  const fact = (payload.commands[1] as any).payload;
  check("the range fact carries the value", fact.value, 442);
  check("in the registry's canonical unit", fact.unit, "km");
  check("and keeps NEDC as a qualifier", fact.qualifiers, { measurement_basis: "NEDC" });

  const diff = diffTrimEdit({
    current: {},
    submissions: [{ key: "rated_range_km", valueState: "KNOWN", value: 442, qualifiers: { measurement_basis: "NEDC" } }],
    fields: FIELDS,
  });
  check("the review diff reads as one coherent line", diff[0].label, "Rated driving range");
  check("with the test cycle visible, not dropped", diff[0].proposed, "442 km (NEDC)");
  check("against an honest empty current value", diff[0].current, "—");
  ok("and is marked as a change", diff[0].changed);

  // Coming back after a release, the qualifier has to return too.
  const round = normalizeTrimForEditor({
    payload: {
      specs: {},
      comparable_specs: [{
        field_key: "ev.rated_range_km", value_state: "KNOWN", value: 442, unit: "km",
        qualifiers: { measurement_basis: "NEDC" },
      }],
    },
    fields: FIELDS, powertrain: "BEV",
  }).editableSpecs.rated_range_km;
  check("re-reading prefills the value", round.value, "442");
  check("and the NEDC comes back with it", round.qualifiers, { measurement_basis: "NEDC" });

  // Re-submitting exactly what came back must be "no changes".
  const unchanged = diffTrimEdit({
    current: { rated_range_km: round },
    submissions: [{ key: "rated_range_km", valueState: "KNOWN", value: 442, qualifiers: { measurement_basis: "NEDC" } }],
    fields: FIELDS,
  });
  ok("re-submitting the same value and qualifier is not a change", !unchanged[0].changed);
  const changedCycle = diffTrimEdit({
    current: { rated_range_km: round },
    submissions: [{ key: "rated_range_km", valueState: "KNOWN", value: 442, qualifiers: { measurement_basis: "WLTP" } }],
    fields: FIELDS,
  });
  ok("changing only the test cycle IS a change (it is part of the fact's identity)", changedCycle[0].changed);
}

// =====================================================================
console.log("\nTEST 7 — a brand-new trim carries its specs in the same save");
// =====================================================================
{
  const { payload } = buildTrimEditBatch({
    batchId: "b3", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "",
    evidence: EVIDENCE, canonicalModelId: "aion.aion_es",
    brand: { id: "aion", nameEn: "Aion" }, generationCode: "aes",
    generationId: "aion.aion_es.aes",
    identity: { name: "Ultra Dual Motor", powertrain: "BEV" },
    fields: FIELDS,
    submissions: [
      { key: "seats", valueState: "KNOWN", value: 5, qualifiers: {} },
      { key: "rated_range_km", valueState: "KNOWN", value: 500, qualifiers: { measurement_basis: "CLTC" } },
    ],
  });
  check("one batch creates the trim and both of its facts", payload.commands.length, 3);
  const [bundle, ...specs] = payload.commands as any[];
  ok("the new trim carries no canonical_id (the writer assigns identity)",
    !("canonical_id" in bundle.payload.trims[0]));
  ok("the spec commands carry no trim_id either",
    specs.every((c: any) => !("trim_id" in c.payload) && !("canonical_id" in c)));

  // The whole point: no slug algorithm in TypeScript. "Dual Motor" is exactly
  // the name vehreg/normalize.py's folder mangles (it strips "motor"), so a
  // reimplementation here would attach these facts to a trim that never exists.
  check("they name the trim by reference for the writer to resolve",
    specs[0].payload.trim_ref,
    { generation_id: "aion.aion_es.aes", name: "Ultra Dual Motor", powertrain: "BEV" });
  const builderSource = fs.readFileSync("lib/canonical-command-builder.ts", "utf8");
  ok("the builder computes no slug of its own",
    !/slug|toLowerCase\(\)[\s\S]{0,40}replace\([\s\S]{0,20}_/.test(builderSource)
    || !/function\s+slug/.test(builderSource));
  ok("nothing in lib/ reimplements the trim identity rule",
    !fs.readdirSync("lib").some((name) => name.endsWith(".ts")
      && /trim_id\s*=\s*`?\$\{?\w+\}?\.trim\./.test(fs.readFileSync(`lib/${name}`, "utf8"))));
}

// =====================================================================
console.log("\nTEST — the form and the canonical writer agree on what is valid");
// =====================================================================
{
  // The exact bug the user reported: the UI took 0 and the writer rejected it.
  // MarketTrim.validate() refuses 0 for the columns it owns.
  check("battery capacity 0 is rejected by the form, as the writer would",
    validateFieldValue(byKey("battery_kwh"), "0"), { ok: false, message: "ต้องมากกว่า 0" });
  check("seats 0 is rejected", validateFieldValue(byKey("seats"), "0").ok, false);
  check("seats 4.5 is rejected as non-integer", validateFieldValue(byKey("seats"), "4.5").ok, false);
  check("seats 5 is accepted and coerced to a number",
    validateFieldValue(byKey("seats"), "5"), { ok: true, value: 5 });
  check("a negative length is rejected", validateFieldValue(byKey("length_mm"), "-1").ok, false);
  check("a non-numeric length is rejected", validateFieldValue(byKey("length_mm"), "abc").ok, false);
  check("a blank field is untouched, not invalid",
    validateFieldValue(byKey("length_mm"), ""), { ok: true, value: null });
  check("battery capacity 55.2 keeps its decimal",
    validateFieldValue(byKey("battery_kwh"), "55.2"), { ok: true, value: 55.2 });
  check("an off-list drivetrain is rejected", validateFieldValue(byKey("drivetrain"), "6WD").ok, false);
  check("FWD is accepted", validateFieldValue(byKey("drivetrain"), "FWD"), { ok: true, value: "FWD" });
  check("a boolean ADAS field takes true", validateFieldValue(byKey("safety_aeb"), "true"), { ok: true, value: true });
  check("a boolean ADAS field rejects prose", validateFieldValue(byKey("safety_aeb"), "yes").ok, false);
  check("a spec-only number may legitimately be 0",
    validateFieldValue(byKey("co2_g_km"), "0"), { ok: true, value: 0 });

  // Cross-field rules MarketTrim.validate() enforces that no single box can see.
  check("a wheelbase longer than the car is caught before the writer sees it",
    validateTrimConsistency({ wheelbase_mm: 4900, length_mm: 4810 }, "BEV").wheelbase_mm,
    "ระยะฐานล้อต้องน้อยกว่าความยาวตัวรถ");
  check("a sane wheelbase passes",
    validateTrimConsistency({ wheelbase_mm: 2750, length_mm: 4810 }, "BEV"), {});
  ok("a combustion engine on a BEV is caught",
    Boolean(validateTrimConsistency({ engine_cc: 1500 }, "BEV").engine_cc));
}

// =====================================================================
console.log("\nTEST — the whole AION ES acceptance entry, compiled once");
// =====================================================================
{
  const entered: Array<[string, string | number | boolean, Record<string, string>]> = [
    ["drivetrain", "FWD", {}],
    ["motor_type", "PMSM", {}],
    ["max_power_kw", 100, {}],
    ["max_torque_nm", 225, {}],
    ["battery_kwh", 55.2, {}],
    ["battery_chemistry", "LFP", {}],
    ["battery_supplier", "CATL", {}],
    ["rated_range_km", 442, { measurement_basis: "NEDC" }],
    ["seats", 5, {}],
    ["length_mm", 4810, {}],
    ["width_mm", 1880, {}],
    ["height_mm", 1545, {}],
    ["wheelbase_mm", 2750, {}],
    ["tire_front", "215/55 R17", {}],
    ["tire_rear", "215/55 R17", {}],
  ];
  const submissions = entered.map(([key, value, qualifiers]) =>
    ({ key, valueState: "KNOWN" as const, value, qualifiers }));

  const { payload } = buildTrimEditBatch({
    batchId: "aion-acceptance", year: 2026, submittedAt: "2026-01-01T00:00:00Z",
    reason: "", evidence: { sourceKind: "ADMIN", reviewedAt: "2026-01-01" },
    canonicalModelId: "aion.aion_es", brand: { id: "aion", nameEn: "Aion" },
    generationCode: "aes", generationId: "aion.aion_es.aes",
    existingTrimId: COMFORT.canonical_id,
    identity: { name: "Comfort / Private Use", powertrain: "BEV" },
    fields: FIELDS, submissions,
  });
  check("one save is one batch", payload.batch_id, "aion-acceptance");
  check("one trim patch plus one fact per entered field", payload.commands.length, 1 + 15);
  const trimRow = (payload.commands[0] as any).payload.trims[0];
  check("the eight MarketTrim columns the concepts own are all patched",
    [trimRow.drivetrain, trimRow.battery_kwh, trimRow.seats, trimRow.length_mm,
      trimRow.width_mm, trimRow.height_mm, trimRow.wheelbase_mm, trimRow.tire_front],
    ["FWD", 55.2, 5, 4810, 1880, 1545, 2750, "215/55 R17"]);
  ok("the trim keeps its canonical_id so this edits rather than forks",
    trimRow.canonical_id === COMFORT.canonical_id);

  const diff = diffTrimEdit({ current: {}, submissions, fields: FIELDS });
  check("the review shows one row per concept, not one per backend write", diff.length, 15);
  ok("every row is marked changed (the trim was empty)", diff.every((row) => row.changed));
  check("the range row reads with its unit and test cycle",
    diff.find((row) => row.field === "rated_range_km")!.proposed, "442 km (NEDC)");
  check("the battery manufacturer row reads plainly",
    diff.find((row) => row.field === "battery_supplier")!.proposed, "CATL");
  ok("no diff row mentions MarketTrim, APPEND_SPEC or a registry key",
    !diff.some((row) => /MarketTrim|APPEND_SPEC|vehicle\.|battery\.|fitment\./.test(row.label)));

  // Every fact the writer will see must satisfy SpecLedger._validate_fact,
  // which requires observed_at, source and source_ref on every single one.
  const facts = (payload.commands.slice(1) as any[]).map((c) => c.payload);
  ok("every fact carries observed_at, source and source_ref",
    facts.every((f) => f.observed_at && f.source && f.source_ref));
  ok("every fact names a real registry field",
    facts.every((f) => REGISTRY.some((d) => d.key === f.field_key)));
  ok("every numeric fact carries exactly its registry canonical unit",
    facts.every((f) => {
      const definition = REGISTRY.find((d) => d.key === f.field_key)!;
      return definition.valueType !== "NUMBER" || f.unit === definition.canonicalUnit;
    }));
  ok("no fact carries a fact_id (the writer derives it from the resolved trim)",
    facts.every((f) => !("fact_id" in f)));
}

// =====================================================================
console.log("\nTEST — clearing, not-applicable, and no-change stay distinguishable");
// =====================================================================
{
  const current = {
    seats: { value: "5", valueState: "KNOWN" as const, qualifiers: {}, origin: "trim" as const },
    engine_cc: { value: "", valueState: "UNKNOWN" as const, qualifiers: {}, origin: "none" as const },
  };
  const diff = diffTrimEdit({
    current,
    submissions: [{ key: "seats", valueState: "KNOWN", value: 5, qualifiers: {} }],
    fields: FIELDS,
  });
  ok("re-submitting an identical value is not a change", !diff[0].changed);

  const { payload } = buildTrimEditBatch({
    batchId: "b4", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "",
    evidence: EVIDENCE, canonicalModelId: "m", brand: { id: "b", nameEn: "B" },
    generationCode: "g", generationId: "m.g", existingTrimId: "m.g.trim.t",
    identity: { name: "T", powertrain: "BEV" }, fields: FIELDS,
    submissions: [
      { key: "seats", valueState: "UNKNOWN", value: null, qualifiers: {} },
      { key: "tire_front", valueState: "UNKNOWN", value: null, qualifiers: {} },
      { key: "drivetrain", valueState: "UNKNOWN", value: null, qualifiers: {} },
      { key: "battery_chemistry", valueState: "NOT_APPLICABLE", value: null, qualifiers: {} },
    ],
  });
  const trimRow = (payload.commands[0] as any).payload.trims[0];
  check("clearing a numeric column writes null, and the key is present so update() overwrites",
    [trimRow.seats, "seats" in trimRow], [null, true]);
  check("clearing a text column writes an empty string", trimRow.tire_front, "");
  check("clearing the drivetrain enum writes its own empty value", trimRow.drivetrain, "UNKNOWN");
  const chemistry = (payload.commands as any[]).find((c) => c.payload.field_key === "battery.chemistry").payload;
  check("NOT_APPLICABLE is recorded as a state, never as a zero or an empty string",
    [chemistry.value_state, chemistry.value, chemistry.unit], ["NOT_APPLICABLE", null, ""]);
  check("describeValue renders an unknown as an em dash, not as 'undefined'",
    describeValue({ value: "", valueState: "UNKNOWN", qualifiers: {} }), "—");
  check("describeValue names a not-applicable plainly",
    describeValue({ value: "", valueState: "NOT_APPLICABLE", qualifiers: {} }), "not applicable");
}

// =====================================================================
console.log("\nunchanged behaviour that still has to hold");
// =====================================================================
{
  check("a blank reason still becomes a readable audit line",
    composeReason({ sourceKind: "ADMIN", reviewedAt: "2026-01-01" }, ""),
    "Manual edit via Canonical Vehicle Editor");
  ok("batch source.kind stays ADMIN (the queue helper requires it)",
    buildTrimEditBatch({
      batchId: "b5", year: 2026, submittedAt: "2026-01-01T00:00:00Z", reason: "",
      evidence: { sourceKind: "ADMIN", reviewedAt: "2026-01-01" }, canonicalModelId: "m",
      brand: { id: "b", nameEn: "B" }, generationCode: "g", generationId: "m.g",
      identity: { name: "T", powertrain: "BEV" }, fields: FIELDS, submissions: [],
    }).payload.source.kind === "ADMIN");

  const existing = [
    { canonicalId: "t1", generationId: "gen1", name: "Max Plus", powertrain: "BEV" },
    { canonicalId: "t3", generationId: "gen2", name: "Max Plus", powertrain: "BEV" },
  ];
  check("same generation + powertrain + normalized name is flagged, never auto-merged",
    findDuplicateMarketTrim(existing, { generationId: "gen1", name: "  MAX   plus ", powertrain: "bev" })?.canonicalId, "t1");
  ok("editing a trim against itself is not its own duplicate",
    findDuplicateMarketTrim(existing, { generationId: "gen1", name: "Max Plus", powertrain: "BEV", excludeCanonicalId: "t1" }) === null);
  check("normalizedTrimName folds case/spacing/punctuation", normalizedTrimName("  Max-Plus!! "), "max plus");

  check("removing the only url under a kind drops that kind",
    applySourceRefEdits({ ecosticker: ["uuid-1"], official_site: ["u"] },
      { remove: [{ kind: "official_site", url: "u" }], add: [] }), { ecosticker: ["uuid-1"] });
  ok("a different release_id is stale", isStaleRelease("rel-1", "rel-2"));
  ok("a missing page fingerprint never blocks", !isStaleRelease("", "rel-2"));

  check("resolvedSpecsFromPayload falls back to current_spec_facts rows when the payload embeds none",
    resolvedSpecsFromPayload({ specs: {} },
      [{ field_key: "battery.supplier", value_state: "KNOWN", value: "CATL" }]).get("battery.supplier")?.value,
    "CATL");
}

// =====================================================================
console.log("\nsource-text regression — the shape the mandate requires");
// =====================================================================
{
  const form = fs.readFileSync("components/admin/TrimEditorForm.tsx", "utf8");
  ok("the editor form is one form for the whole trim",
    (form.match(/<form/g) || []).length === 1);
  ok("it renders from the shared field catalog, not a hand-written field list",
    /fieldsByCategory\(props\.fields\)/.test(form));
  ok("it validates with the very function the server action uses",
    /validateFieldValue\(field, raw\)/.test(form));
  ok("it shows a field's error beside that field", /trimFieldMessage/.test(form) && /serverError/.test(form));
  ok("qualifiers render next to their own field", /field\.qualifiers\.map/.test(form));
  ok("the source context is chosen once for the whole edit, not per field",
    (form.match(/name="evidence_kind"/g) || []).length === 1);
  ok("no field-level source or reason input exists",
    !/evidence_ref_\$\{/.test(form) && !/reason__/.test(form));

  const actions = fs.readFileSync("app/admin/vehicle-editor-actions.ts", "utf8");
  ok("prepareTrimEdit is admin-gated",
    /export async function prepareTrimEdit[\s\S]{0,300}isAdmin\(\)/.test(actions));
  ok("it reads the normalized editor state, never the raw payload nesting",
    /existing\?\.editor\.editableSpecs/.test(actions)
    && !/existing\.payload\./.test(actions) && !/\.payload\.drivetrain/.test(actions));
  ok("it returns validation errors to the form instead of throwing to the boundary",
    /return \{ formError: "", fieldErrors \}/.test(actions));
  ok("a stale release comes back to the form too, not as a crash",
    /isStaleRelease\(pageReleaseId, workspace\.releaseId\)\)\s*\{\s*return/.test(actions));
  ok("it compiles through the one unified builder", /buildTrimEditBatch\(/.test(actions));
  ok("the old add-one-spec-at-a-time flow is gone",
    ["addSpecDraftEntry", "removeSpecDraftEntry", "discardSpecDraft", "prepareSpecDraftReview",
      "spec_na__", "spec__$"].every((gone) => !actions.includes(gone)));
  ok("nothing requires a reason or an evidence ref",
    !/requiredField\(formData, "reason"/.test(actions) && !/evidenceUrl/.test(actions));
  ok("the only write path is still enqueueCanonicalInputBatch",
    !/adminDb\(\)/.test(actions) && !/\.from\(["'`](current_|canonical_)/.test(actions));

  const page = fs.readFileSync("app/admin/(secure)/vehicles/[modelId]/page.tsx", "utf8");
  // The page still has its own Model/Generation form (where `seats` is the
  // generation's, a different thing from a trim's), but it must no longer
  // render a single MarketTrim column: those all come from the catalog now.
  ok("the page no longer renders MarketTrim columns itself",
    ["tire_front", "tire_rear", "drivetrain", "engine_cc", "battery_kwh", "wheelbase_mm",
      "transmission", "wheel_front"].every((column) => !page.includes(`name="${column}"`)));
  ok("the page delegates the whole trim form to the shared component",
    /<TrimEditorForm/.test(page) && !/function TrimEditor\b/.test(page) && !/function SpecField\b/.test(page));
  ok("creating a trim no longer tells the admin to come back later for specs",
    !/สร้าง trim ก่อน/.test(page));
  ok("generation code is never an editable input (identity-preserving)",
    !/name="code"/.test(page) && !/name="generation_code"/.test(page));

  const state = fs.readFileSync("lib/trim-editor-state.ts", "utf8");
  ok("normalization prefers payload.specs", /isRecord\(payload\.specs\)\) return payload\.specs/.test(state));
  ok("no '@/' alias imports in the pure editor modules",
    !/from "@\//.test(state)
    && !/from "@\//.test(fs.readFileSync("lib/trim-editor-fields.ts", "utf8"))
    && !/from "@\//.test(fs.readFileSync("lib/canonical-command-builder.ts", "utf8")));

  const css = fs.readFileSync("app/globals.css", "utf8");
  for (const cls of ["trimForm", "trimField", "trimQualifiers", "trimFieldMessage", "trimNotApplicable"]) {
    ok(`.${cls} is styled (not a class that renders unstyled)`, new RegExp(`\\.${cls}[\\{,\\s]`).test(css));
  }
}

// =====================================================================
console.log("\nsource-text regression — migrations");
// =====================================================================
{
  const v35 = fs.readFileSync("supabase/migration_v35_admin_edit_sessions.sql", "utf8");
  ok("v35 is labelled as applied to production and not to be edited",
    /APPLIED to production/.test(v35) && /Do not edit this file/.test(v35));
  ok("v35 still describes the schema production actually has",
    /'MODEL_GENERATION', 'MARKET_TRIM', 'SPEC_DRAFT'/.test(v35) && /draft_entries/.test(v35));

  const v36 = fs.readFileSync("supabase/migration_v36_admin_edit_sessions_trim_kind.sql", "utf8");
  ok("v36 migrates the applied v35 state forward", /MARKET_TRIM/.test(v36) && /'TRIM'/.test(v36));
  ok("v36 relabels rather than deletes rows", /update public\.admin_edit_sessions/.test(v36)
    && !/delete from/i.test(v36) && !/truncate/i.test(v36) && !/drop table/i.test(v36));
  ok("v36 retires DRAFT rows instead of dropping them", /set status = 'CONSUMED'/.test(v36));
  // The old check is what rejects the new value, so the constraints have to
  // come off before the rows are relabelled. Proven for real against a live
  // Postgres in tests/test_admin_edit_sessions_migration.py; asserted here so
  // the order cannot be quietly swapped back.
  ok("v36 drops the old constraints before relabelling rows",
    v36.indexOf("drop constraint if exists admin_edit_sessions_kind_check")
      < v36.indexOf("update public.admin_edit_sessions"));
  ok("v36 re-adds the new constraints after relabelling rows",
    v36.lastIndexOf("update public.admin_edit_sessions")
      < v36.indexOf("add constraint admin_edit_sessions_kind_check"));
  ok("v36 is one transaction, so a half-applied migration is impossible",
    /^begin;/m.test(v36) && /^commit;/m.test(v36));
  ok("v36 is re-runnable", (v36.match(/drop constraint if exists/g) || []).length >= 3
    && /drop column if exists/.test(v36));

  for (const [name, sql] of [["v35", v35]] as const) {
    ok(`${name} keeps RLS on`, /enable row level security/.test(sql));
    ok(`${name} revokes public/anon/authenticated`,
      /revoke all on table public\.admin_edit_sessions from public, anon, authenticated/.test(sql));
    ok(`${name} grants only service_role`, !/grant[^;]*to (anon|authenticated)/.test(sql));
  }
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall trim editor checks passed");
process.exit(failed ? 1 : 0);
