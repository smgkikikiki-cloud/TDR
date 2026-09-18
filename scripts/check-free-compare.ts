import {
  FREE_COMPARE_GROUPS,
  compareGroupDefinitions,
  compareValue,
  indexSpecFields,
  rowIsDifferent,
  visibleCompareGroups,
  type CompareSpecField,
  type FreeCompareTrim,
} from "../lib/free-compare.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const a: FreeCompareTrim = {
  id: "a", price_baht: 899000, segment: "B", body_type: "CROSSOVER",
  powertrain: "BEV", battery_kwh: 58.9, drivetrain: "FWD",
  length_mm: 4380, width_mm: 1860, height_mm: 1650, seats: 5,
  production_type: "CKD", production_country: "TH",
};
const b: FreeCompareTrim = {
  id: "b", price_baht: 999000, segment: "B", body_type: "CROSSOVER",
  powertrain: "BEV", battery_kwh: 60, drivetrain: "FWD",
  length_mm: 4400, width_mm: 1860, height_mm: 1650, seats: 5,
  production_type: "CBU", production_country: "CN",
};

console.log("free compare — product scope");
const keys = FREE_COMPARE_GROUPS.flatMap((group) => group.rows.map((row) => String(row.key)));
const fitmentKey = (key: string) => key.startsWith("tire_") || key.startsWith("tyre_")
  || /^wheel_(?:front|rear|size)/.test(key);
check("tyre/wheel fitment is not a public compare field", keys.some(fitmentKey), false);
check("wheelbase remains a valid vehicle dimension", keys.includes("wheelbase_mm"), true);
check("price formats from exact trim", compareValue(a, "price"), "฿899,000");

console.log("\nfree compare — honest missing data");
const all = visibleCompareGroups([a, b]);
check("empty wheelbase row is hidden", all.flatMap((group) => group.rows).some((row) => row.key === "wheelbase_mm"), false);
check("missing-vs-known is a difference", rowIsDifferent([a, { ...b, battery_kwh: null }], "battery_kwh"), true);
check("same body is not a difference", rowIsDifferent([a, b], "body_type"), false);

console.log("\nfree compare — differences-only mode");
const diff = visibleCompareGroups([a, b], true).flatMap((group) => group.rows.map((row) => row.key));
check("different price remains", diff.includes("price"), true);
check("different production type remains", diff.includes("production_type"), true);
check("same drivetrain disappears", diff.includes("drivetrain"), false);

console.log("\nfree compare — comparable specs reach the reader");
// A handful of real registry definitions, in the shape spec-field-registry.ts
// produces. The point of the registry is that a field becomes comparable when
// it is defined, so the rows here are derived, never listed.
const FIELDS: CompareSpecField[] = [
  { key: "safety.airbag_count", group: "safety", labelTh: "จำนวนถุงลมนิรภัย", valueType: "NUMBER", canonicalUnit: "ถุง", displayPrecision: 0 },
  { key: "safety.aeb", group: "safety", labelTh: "ระบบเบรกฉุกเฉินอัตโนมัติ", valueType: "BOOLEAN" },
  { key: "charging.dc_max_kw", group: "charging", labelTh: "ชาร์จเร็ว DC สูงสุด", valueType: "NUMBER", canonicalUnit: "kW", displayPrecision: 0 },
  { key: "ev.rated_range_km", group: "efficiency", labelTh: "ระยะทางวิ่งที่ประกาศ", valueType: "NUMBER", canonicalUnit: "km", displayPrecision: 0 },
  { key: "engine.displacement_cc", group: "powertrain", labelTh: "ความจุกระบอกสูบ", valueType: "NUMBER", canonicalUnit: "cc", displayPrecision: 0 },
];
const definitions = indexSpecFields(FIELDS);
const derived = compareGroupDefinitions(FIELDS).flatMap((group) => group.rows.map((row) => String(row.key)));
check("a registry field becomes a compare row without this file listing it",
  derived.includes("spec:safety.aeb"), true);
check("a field a built-in row already shows is not printed twice",
  derived.filter((key) => key.includes("displacement_cc") || key === "engine_cc"), ["engine_cc"]);
check("a field a built-in row already shows is not duplicated as a spec row",
  derived.includes("spec:ev.rated_range_km"), false);

const withSpecs: FreeCompareTrim = {
  id: "c", powertrain: "BEV", engine_cc: null, battery_kwh: 60,
  comparable_specs: [
    { field_key: "safety.airbag_count", value: 6, value_state: "KNOWN", unit: "ถุง" },
    { field_key: "safety.aeb", value: true, value_state: "KNOWN" },
    { field_key: "charging.dc_max_kw", value: 150, value_state: "KNOWN", unit: "kW" },
    { field_key: "ev.rated_range_km", value: 442, value_state: "KNOWN", unit: "km",
      qualifiers: { measurement_basis: "NEDC" } },
    { field_key: "performance.top_speed_kmh", value: null, value_state: "UNKNOWN" },
  ],
};
check("a numeric fact carries its unit", compareValue(withSpecs, "spec:safety.airbag_count", definitions), "6 ถุง");
check("a boolean fact reads as presence", compareValue(withSpecs, "spec:safety.aeb", definitions), "มี");
check("a measured figure keeps the basis it was measured on",
  compareValue(withSpecs, "range", definitions), "442 km (NEDC)");
check("an UNKNOWN fact is blank, not the word UNKNOWN",
  compareValue(withSpecs, "spec:performance.top_speed_kmh", definitions), null);

// The ledger is the better answer where it has one; the MarketTrim column is
// what is left when it does not.
const columnOnly: FreeCompareTrim = { id: "d", battery_kwh: 58.9 };
check("the column answers when the ledger has no fact",
  compareValue(columnOnly, "battery_kwh", definitions), "58.9 kWh");
const ledgerWins: FreeCompareTrim = {
  id: "e", battery_kwh: 58.9,
  comparable_specs: [{ field_key: "battery.catalog_capacity_kwh", value: 60.2, value_state: "KNOWN", unit: "kWh" }],
};
check("a dated fact beats the catalogue column",
  compareValue(ledgerWins, "battery_kwh", definitions), "60.2 kWh");
// battery.catalog_capacity_kwh is deliberately absent from FIELDS above: a
// fact for a field this build does not define must still print the number the
// source stated, not a rounded one.
check("an undefined field is not silently rounded",
  compareValue({ id: "f", comparable_specs: [
    { field_key: "battery.gross_capacity_kwh", value: 77.4, value_state: "KNOWN", unit: "kWh" }] },
    "spec:battery.gross_capacity_kwh", definitions), "77.4 kWh");
check("a defined precision still rounds",
  compareValue({ id: "g", comparable_specs: [
    { field_key: "charging.dc_max_kw", value: 149.6, value_state: "KNOWN", unit: "kW" }] },
    "spec:charging.dc_max_kw", definitions), "150 kW");

const specGroups = visibleCompareGroups([withSpecs, columnOnly], false, FIELDS);
check("a spec group with no values at all stays hidden",
  specGroups.some((group) => group.rows.some((row) => row.key === "spec:performance.top_speed_kmh")), false);
check("safety reaches the table", specGroups.some((group) => group.title.includes("ความปลอดภัย")), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall free compare checks passed");
process.exit(failed ? 1 : 0);
