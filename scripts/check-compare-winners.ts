import {
  evaluateCompareWinner, PRESENCE_ADVANTAGE_FIELDS, QUANTITATIVE_WINNER_FIELDS,
} from "../lib/compare-winners.ts";
import { indexSpecFields, type CompareSpecField, type FreeCompareTrim, type ResolvedSpec } from "../lib/free-compare.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
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

console.log("\n1 — higher-better numeric winner");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b], "spec:powertrain.max_power_kw", definitions);
  check("mode is QUANTITATIVE_WINNER", result.comparisonMode, "QUANTITATIVE_WINNER");
  check("comparable", result.comparable, true);
  check("the higher power wins", result.bestIndexes, [1]);
}

console.log("\n2 — lower-better numeric winner");
{
  const a = trim("a", [spec("performance.acceleration_0_100_s", 8.9, { measurement_basis: "MANUFACTURER" })]);
  const b = trim("b", [spec("performance.acceleration_0_100_s", 6.4, { measurement_basis: "MANUFACTURER" })]);
  const result = evaluateCompareWinner([a, b], "spec:performance.acceleration_0_100_s", definitions);
  check("the faster (lower) time wins", result.bestIndexes, [1]);
}

console.log("\n3 — exact tie");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b], "spec:powertrain.max_power_kw", definitions);
  check("comparable stays true on a tie", result.comparable, true);
  check("both indexes are returned, nobody alone wins", result.bestIndexes, [0, 1]);
}

console.log("\n4 — three-vehicle comparison with one winner");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 120, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const c = trim("c", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b, c], "spec:powertrain.max_power_kw", definitions);
  check("only the middle car (index 1) wins", result.bestIndexes, [1]);
}

console.log("\n5 — three-vehicle comparison with tied winners");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const c = trim("c", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b, c], "spec:powertrain.max_power_kw", definitions);
  check("both 204 kW cars tie for the win", result.bestIndexes, [0, 2]);
}

console.log("\n6 — missing value does not become loser or winner");
{
  const a = trim("a", [spec("powertrain.max_power_kw", 150, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const b = trim("b", []); // no fact at all for this field
  const c = trim("c", [spec("powertrain.max_power_kw", 204, { output_scope: "MOTOR", rating_basis: "PEAK" })]);
  const result = evaluateCompareWinner([a, b, c], "spec:powertrain.max_power_kw", definitions);
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

console.log("\n10 — incompatible range qualifiers receive no winner");
{
  const a = trim("a", [spec("ev.rated_range_km", 480, { measurement_basis: "WLTP", range_scope: "FULL" })]);
  const b = trim("b", [spec("ev.rated_range_km", 510, { measurement_basis: "NEDC", range_scope: "FULL" })]);
  const result = evaluateCompareWinner([a, b], "spec:ev.rated_range_km", definitions);
  check("WLTP vs NEDC is not comparable", result.comparable, false);
  check("no winner despite 510 > 480", result.bestIndexes, []);
}

console.log("\n11 — incompatible charging SOC windows receive no winner");
{
  // The spec's own example: 25 minutes at 30-80% is not "better" than 30
  // minutes at 10-80%.
  const a = trim("a", [spec("charging.dc_time_min", 25, { soc_from: "30", soc_to: "80", charger_power_kw: "150" })]);
  const b = trim("b", [spec("charging.dc_time_min", 30, { soc_from: "10", soc_to: "80", charger_power_kw: "150" })]);
  const result = evaluateCompareWinner([a, b], "spec:charging.dc_time_min", definitions);
  check("different SOC windows are not comparable", result.comparable, false);
  check("no winner despite 25 < 30", result.bestIndexes, []);
}

console.log("\n12 — compatible qualifiers allow winner calculation");
{
  const a = trim("a", [spec("ev.rated_range_km", 480, { measurement_basis: "WLTP", range_scope: "FULL" })]);
  const b = trim("b", [spec("ev.rated_range_km", 510, { measurement_basis: "WLTP", range_scope: "FULL" })]);
  const result = evaluateCompareWinner([a, b], "spec:ev.rated_range_km", definitions);
  check("same measurement_basis and range_scope is comparable", result.comparable, true);
  check("the longer WLTP range wins", result.bestIndexes, [1]);
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
  const result = evaluateCompareWinner([a, b], "power", definitions);
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
