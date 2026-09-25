import {
  evaluateCompareWinner, PRESENCE_ADVANTAGE_FIELDS, QUANTITATIVE_WINNER_FIELDS,
} from "../lib/compare-winners.ts";
import {
  indexSpecFields, qualifierContextKey,
  type CompareRowKey, type CompareSpecField, type FreeCompareTrim, type ResolvedSpec,
} from "../lib/free-compare.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

/** The exact row key production code (lib/free-compare.ts's
 *  compareGroupDefinitions) would generate for one field's context -- a
 *  caller always evaluates a specific basis, never a bare key on a field
 *  that has more than one in play. Bare `base` (no qualifiers) reproduces
 *  the unsuffixed key a field with nothing to disambiguate keeps. */
function rowKeyFor(base: string, qualifiers: Record<string, unknown> = {},
                   qualifierNames: string[] = []): CompareRowKey {
  const context = qualifierContextKey(qualifiers, qualifierNames);
  return (context ? `${base}::${context}` : base) as CompareRowKey;
}

// A handful of real registry definitions, in the exact shape
// lib/spec-field-registry.ts produces (schema confirmed against
// automotive/vehicle_master/vehreg/data/2026/product/comparable_specs/registry.json).
const FIELDS: CompareSpecField[] = [
  { key: "powertrain.max_power_kw", group: "powertrain", labelTh: "กำลังสูงสุด", valueType: "NUMBER",
    canonicalUnit: "kW", comparisonRule: "HIGHER_BETTER", comparisonQualifiers: ["output_scope", "rating_basis"] },
  { key: "performance.acceleration_0_100_s", group: "performance", labelTh: "0-100 กม./ชม.", valueType: "NUMBER",
    canonicalUnit: "s", comparisonRule: "LOWER_BETTER", comparisonQualifiers: ["measurement_basis"] },
  { key: "ev.rated_range_km", group: "ev", labelTh: "ระยะทางวิ่งไฟฟ้า", valueType: "NUMBER",
    canonicalUnit: "km", comparisonRule: "HIGHER_BETTER", comparisonQualifiers: ["measurement_basis", "range_scope"] },
  { key: "charging.dc_time_min", group: "charging", labelTh: "เวลาชาร์จ DC", valueType: "NUMBER",
    canonicalUnit: "min", comparisonRule: "LOWER_BETTER",
    comparisonQualifiers: ["soc_from", "soc_to", "charger_power_kw"] },
  { key: "safety.aeb", group: "safety", labelTh: "เบรกฉุกเฉินอัตโนมัติ", valueType: "BOOLEAN",
    comparisonRule: "PRESENCE" },
  // In the real registry vehicle.seats is HIGHER_BETTER -- deliberately not
  // in QUANTITATIVE_WINNER_FIELDS (section 3/6 of the spec: more seats is a
  // trade-off, not a win), so this must stay NEUTRAL however the registry
  // tags it.
  { key: "vehicle.seats", group: "vehicle", labelTh: "จำนวนที่นั่ง", valueType: "NUMBER",
    canonicalUnit: "seat", comparisonRule: "HIGHER_BETTER" },
];
const definitions = indexSpecFields(FIELDS);

function spec(fieldKey: string, value: unknown, qualifiers: Record<string, string> = {},
             valueState: string = "KNOWN"): ResolvedSpec {
  return { field_key: fieldKey, value, value_state: valueState, qualifiers };
}

function trim(id: string, specs: ResolvedSpec[]): FreeCompareTrim {
  return { id, comparable_specs: specs };
}

console.log("compare winners — allowlists reuse real registry keys");
check("power is quantitative-winner eligible", QUANTITATIVE_WINNER_FIELDS.has("powertrain.max_power_kw"), true);
check("aeb is presence-advantage eligible", PRESENCE_ADVANTAGE_FIELDS.has("safety.aeb"), true);
check("seats is in neither allowlist despite registry HIGHER_BETTER",
  QUANTITATIVE_WINNER_FIELDS.has("vehicle.seats") || PRESENCE_ADVANTAGE_FIELDS.has("vehicle.seats"), false);
check("panoramic roof stays out of the presence allowlist (spec section 6)",
  PRESENCE_ADVANTAGE_FIELDS.has("comfort.panoramic_roof"), false);

const powerKey = rowKeyFor("spec:powertrain.max_power_kw", { output_scope: "MOTOR", rating_basis: "PEAK" },
  ["output_scope", "rating_basis"]);

console.log("\n1 — higher-better numeric winner");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b], powerKey, definitions);
  check("mode is QUANTITATIVE_WINNER", result.comparisonMode, "QUANTITATIVE_WINNER");
  check("comparable", result.comparable, true);
  check("the higher power wins", result.bestIndexes, [1]);
}

console.log("\n2 — lower-better numeric winner");
{
  const a = trim("a", [spec("performance.acceleration_0_100_s", 8.9, { measurement_basis: "MANUFACTURER" })]);
  const b = trim("b", [spec("performance.acceleration_0_100_s", 6.4, { measurement_basis: "MANUFACTURER" })]);
  const key = rowKeyFor("spec:performance.acceleration_0_100_s", { measurement_basis: "MANUFACTURER" }, ["measurement_basis"]);
  const result = evaluateCompareWinner([a, b], key, definitions);
  check("the faster (lower) time wins", result.bestIndexes, [1]);
}

console.log("\n3 — exact tie (150/150 implies no advantage, nobody is painted a winner)");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b], powerKey, definitions);
  check("comparable stays true on a tie", result.comparable, true);
  check("nobody is highlighted -- an exact tie is not a comparative advantage",
    result.bestIndexes, []);
}

console.log("\n3b — three-way exact tie is also nobody's win");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const c = trim("c", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b, c], powerKey, definitions);
  check("comparable stays true", result.comparable, true);
  check("no winner among three identical values", result.bestIndexes, []);
}

console.log("\n4 — three-vehicle comparison with one winner");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 120, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const c = trim("c", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b, c], powerKey, definitions);
  check("only the middle car (index 1) wins", result.bestIndexes, [1]);
}

console.log("\n5 — three-vehicle comparison with tied winners (a partial tie, unlike case 3)");
{
  // Not every value agrees here (204/150/204), so this is not the "no
  // advantage" case above -- the two 204s genuinely beat the 150 and both
  // must still be highlighted.
  const a = trim("a", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const c = trim("c", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b, c], powerKey, definitions);
  check("both 204 kW cars tie for the win", result.bestIndexes, [0, 2]);
}

console.log("\n6 — missing value does not become loser or winner");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", []); // no fact at all for this field
  const c = trim("c", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b, c], powerKey, definitions);
  check("comparable among the two known values", result.comparable, true);
  check("the missing trim (index 1) never appears in bestIndexes",
    result.bestIndexes.includes(1), false);
  check("the actual higher value still wins", result.bestIndexes, [2]);
}

console.log("\n7 — unknown boolean is not treated as false");
{
  const a = trim("a", [spec("safety.aeb", true)]);
  const b = trim("b", [spec("safety.aeb", null, {}, "UNKNOWN")]);
  const result = evaluateCompareWinner([a, b], "spec:safety.aeb", definitions);
  check("only one KNOWN boolean is not enough to compare", result.comparable, false);
  check("no winner is declared from one known value against an unknown", result.bestIndexes, []);
}

console.log("\n8 — presence advantage");
{
  const a = trim("a", [spec("safety.aeb", true)]);
  const b = trim("b", [spec("safety.aeb", false)]);
  const result = evaluateCompareWinner([a, b], "spec:safety.aeb", definitions);
  check("mode is PRESENCE_ADVANTAGE", result.comparisonMode, "PRESENCE_ADVANTAGE");
  check("comparable", result.comparable, true);
  check("the trim that has it is the advantage", result.bestIndexes, [0]);
}

console.log("\n8b — presence with no contrast is comparable but has no winner");
{
  const a = trim("a", [spec("safety.aeb", true)]);
  const b = trim("b", [spec("safety.aeb", true)]);
  const result = evaluateCompareWinner([a, b], "spec:safety.aeb", definitions);
  check("comparable (both known)", result.comparable, true);
  check("no advantage when both have it", result.bestIndexes, []);
}

console.log("\n9 — neutral field receives no winner");
{
  const a = trim("a", [spec("vehicle.seats", 5)]);
  const b = trim("b", [spec("vehicle.seats", 7)]);
  const result = evaluateCompareWinner([a, b], "spec:vehicle.seats", definitions);
  check("mode is NEUTRAL even though the registry says HIGHER_BETTER", result.comparisonMode, "NEUTRAL");
  check("never comparable", result.comparable, false);
  check("never a winner", result.bestIndexes, []);
}

console.log("\n10 — a WLTP-only row and an NEDC-only row never produce a winner against each other");
{
  // Row identity already splits by qualifier context (lib/free-compare.ts),
  // so a WLTP fact and an NEDC fact are never even asked about on the same
  // row -- each row only ever sees the trims that answer its own context.
  const a = trim("a", [spec("ev.rated_range_km", 480, { measurement_basis: "WLTP", range_scope: "FULL" })]);
  const b = trim("b", [spec("ev.rated_range_km", 510, { measurement_basis: "NEDC", range_scope: "FULL" })]);
  const wltpKey = rowKeyFor("spec:ev.rated_range_km", { measurement_basis: "WLTP", range_scope: "FULL" },
    ["measurement_basis", "range_scope"]);
  const nedcKey = rowKeyFor("spec:ev.rated_range_km", { measurement_basis: "NEDC", range_scope: "FULL" },
    ["measurement_basis", "range_scope"]);
  check("the WLTP row is not comparable -- only trim a answers it", evaluateCompareWinner([a, b], wltpKey, definitions).comparable, false);
  check("the NEDC row is not comparable either -- only trim b answers it", evaluateCompareWinner([a, b], nedcKey, definitions).comparable, false);
}

console.log("\n11 — a 10-80% SOC row and a 30-80% SOC row never produce a winner against each other");
{
  // The spec's own example: 25 minutes at 30-80% is not "better" than 30
  // minutes at 10-80% -- and now they are not even the same row.
  const a = trim("a", [spec("charging.dc_time_min", 25, { soc_from: "30", soc_to: "80", charger_power_kw: "150" })]);
  const b = trim("b", [spec("charging.dc_time_min", 30, { soc_from: "10", soc_to: "80", charger_power_kw: "150" })]);
  const socNames = ["soc_from", "soc_to", "charger_power_kw"];
  const window3080 = rowKeyFor("spec:charging.dc_time_min", { soc_from: "30", soc_to: "80", charger_power_kw: "150" }, socNames);
  const window1080 = rowKeyFor("spec:charging.dc_time_min", { soc_from: "10", soc_to: "80", charger_power_kw: "150" }, socNames);
  check("the 30-80% row is not comparable -- only trim a answers it", evaluateCompareWinner([a, b], window3080, definitions).comparable, false);
  check("the 10-80% row is not comparable either -- only trim b answers it", evaluateCompareWinner([a, b], window1080, definitions).comparable, false);
}

console.log("\n12 — compatible qualifiers allow winner calculation");
{
  const a = trim("a", [spec("ev.rated_range_km", 480, { measurement_basis: "WLTP", range_scope: "FULL" })]);
  const b = trim("b", [spec("ev.rated_range_km", 510, { measurement_basis: "WLTP", range_scope: "FULL" })]);
  const key = rowKeyFor("spec:ev.rated_range_km", { measurement_basis: "WLTP", range_scope: "FULL" },
    ["measurement_basis", "range_scope"]);
  const result = evaluateCompareWinner([a, b], key, definitions);
  check("same measurement_basis and range_scope is comparable", result.comparable, true);
  check("the longer WLTP range wins", result.bestIndexes, [1]);
}

console.log("\n13 — a trim with two KNOWN contexts for one field is two independently-evaluable rows, not one ambiguous one");
{
  // SpecLedger.resolved() is keyed by (field_key, qualifier_key): a single
  // trim can legitimately carry both a WLTP and an NEDC range fact at once.
  // Row identity means that no longer has to be one row picking a basis (or
  // failing closed) -- it is two rows, each evaluated on its own context,
  // exactly like case 10 but now with a real winner on one of them.
  const a = trim("a", [
    spec("ev.rated_range_km", 480, { measurement_basis: "WLTP", range_scope: "FULL" }),
    spec("ev.rated_range_km", 510, { measurement_basis: "NEDC", range_scope: "FULL" }),
  ]);
  const b = trim("b", [spec("ev.rated_range_km", 490, { measurement_basis: "WLTP", range_scope: "FULL" })]);
  const names = ["measurement_basis", "range_scope"];
  const wltpKey = rowKeyFor("spec:ev.rated_range_km", { measurement_basis: "WLTP", range_scope: "FULL" }, names);
  const nedcKey = rowKeyFor("spec:ev.rated_range_km", { measurement_basis: "NEDC", range_scope: "FULL" }, names);
  const wltpResult = evaluateCompareWinner([a, b], wltpKey, definitions);
  check("the WLTP row compares a's WLTP fact against b's WLTP fact", wltpResult.comparable, true);
  check("b's 490 beats a's 480 on the WLTP row", wltpResult.bestIndexes, [1]);
  const nedcResult = evaluateCompareWinner([a, b], nedcKey, definitions);
  check("the NEDC row is not comparable -- b has no NEDC fact at all", nedcResult.comparable, false);
}

console.log("\n14 — a duplicate KNOWN fact with no distinguishing qualifier is skipped, not guessed, and no longer kills the whole row");
{
  // safety.aeb declares no comparisonQualifiers, so two KNOWN facts for it
  // on the same trim collide on the same (empty) context -- something
  // SpecLedger.resolved()'s own (field_key, qualifier_key) dedup should
  // never actually produce, but a stale or hand-built payload might. The
  // old design failed the whole row closed for every trim when this
  // happened; now only the malformed trim contributes no value, and the
  // other trims still compare normally.
  const a = trim("a", [spec("safety.aeb", true), spec("safety.aeb", false)]);
  const b = trim("b", [spec("safety.aeb", true)]);
  const c = trim("c", [spec("safety.aeb", false)]);
  const result = evaluateCompareWinner([a, b, c], "spec:safety.aeb", definitions);
  check("trim a's undecidable duplicate contributes no value", result.bestIndexes.includes(0), false);
  check("b and c still compare normally despite a's bad data", result.comparable, true);
  check("b (has it) is still the advantage over c (does not)", result.bestIndexes, [1]);
}

console.log("\nextra — a field with no known values at all is never comparable");
{
  const a = trim("a", []);
  const b = trim("b", []);
  const result = evaluateCompareWinner([a, b], "spec:powertrain.max_power_kw", definitions);
  check("zero known values -> not comparable", result.comparable, false);
}

console.log("\nextra — a built-in row backed by the ledger reuses the same policy");
{
  // "power" is a BuiltinCompareRowKey backed by powertrain.max_power_kw
  // (lib/free-compare.ts SPEC_BACKED_ROWS). Winner evaluation must key off
  // the same registry field whether the row came from the ledger via a
  // built-in column or a bare spec: row.
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const builtinPowerKey = rowKeyFor("power", { output_scope: "MOTOR", rating_basis: "PEAK" }, ["output_scope", "rating_basis"]);
  const result = evaluateCompareWinner([a, b], builtinPowerKey, definitions);
  check("built-in 'power' row resolves the same winner as the spec: row", result.bestIndexes, [1]);
}

console.log("\nextra — a built-in row with no ledger fact (only the legacy column) is never comparable");
{
  // trim.torque_nm style legacy columns carry no qualifiers at all, so
  // winner-eligibility must never be inferred from them -- only from an
  // actual resolved ledger fact.
  const a: FreeCompareTrim = { id: "a", torque_nm: 300 };
  const b: FreeCompareTrim = { id: "b", torque_nm: 350 };
  const result = evaluateCompareWinner([a, b], "torque_nm", definitions);
  check("no ledger fact means no winner even though both display a number", result.comparable, false);
}

console.log("\nextra — an unrecognized row key is always NEUTRAL");
{
  const a = trim("a", []);
  const b = trim("b", []);
  const result = evaluateCompareWinner([a, b], "price", definitions);
  check("price has no registry backing and is always neutral", result.comparisonMode, "NEUTRAL");
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall compare winner checks passed");
process.exit(failed ? 1 : 0);
