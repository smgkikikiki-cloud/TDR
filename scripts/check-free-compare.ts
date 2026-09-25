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
import { paginateAll } from "../lib/paginate-all.ts";

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

console.log("\nfree compare — every car in the catalogue can be compared");
// A live proof, not just a text match: drive the real paginateAll() against a
// fake source of 1,300 rows -- more than PostgREST's 1,000-row page cap --
// and confirm it actually walked more than one page rather than trusting a
// single .range() call to have returned everything.
{
  const totalRows = 1_300;
  const allFakeRows = Array.from({ length: totalRows }, (_, i) => ({ id: i }));
  const pagesFetched: Array<[number, number]> = [];
  const rows = await paginateAll(async (from, to) => {
    pagesFetched.push([from, to]);
    return { data: allFakeRows.slice(from, to + 1), error: null };
  });
  check("paginateAll returns every row of a catalogue larger than one page",
    rows.length, totalRows);
  check("paginateAll actually walked more than one page to get there",
    pagesFetched.length > 1, true);
  check("the first page asked for exactly PostgREST's row cap",
    pagesFetched[0], [0, 999]);
  check("the last page is the short one that ends the loop",
    pagesFetched.at(-1), [1000, 1999]);
}
{
  // A source with fewer rows than one page must not fetch a second page at
  // all -- a short first page is itself proof there is nothing left.
  const fewRows = Array.from({ length: 12 }, (_, i) => ({ id: i }));
  let calls = 0;
  const rows = await paginateAll(async (from, to) => {
    calls++;
    return { data: fewRows.slice(from, to + 1), error: null };
  });
  check("a catalogue smaller than one page is read in a single call", calls, 1);
  check("all rows of the short catalogue are still returned", rows.length, 12);
}

// PostgREST returns at most a thousand rows whatever limit is asked for, so a
// single .limit() silently returns a prefix once a table outgrows it. The
// picker's own full-catalogue read (lib/compare-canonical-data.ts) must page
// past that on its own -- it does not reuse lib/canonical-data.ts's allRows()
// because it needs a narrow, picker-only column list, never "*" over the
// full 1,500+ row trim projection with its large JSON columns.
const fs2 = await import("node:fs");
const canonicalData = fs2.readFileSync("lib/canonical-data.ts", "utf8");
const compareCanonicalData = fs2.readFileSync("lib/compare-canonical-data.ts", "utf8");
const paginateAllSource = fs2.readFileSync("lib/paginate-all.ts", "utf8");
check("the model catalogue read is still paged rather than cut off at a limit",
  canonicalData.includes("async function allRows") && canonicalData.includes(".range(from, from + pageSize - 1)"), true);
check("a short page ends the model catalogue's paging", canonicalData.includes("data.length < pageSize"), true);
check("the picker's full trim read pages with .range(), not a single .limit()",
  compareCanonicalData.includes(".range(from, to)") && compareCanonicalData.includes("paginateAll"), true);
check("a short page ends the picker's shared paging loop (never assumes exactly 1,000 more exist)",
  /data\.length < pageSize/.test(paginateAllSource), true);
check("the picker selects an explicit narrow column list, never select(\"*\") over current_market_trims",
  compareCanonicalData.includes("PICKER_COLUMNS") && compareCanonicalData.includes(".select(PICKER_COLUMNS)")
    && !compareCanonicalData.includes('.select("*")'), true);

const pickerRoute = fs2.readFileSync("app/api/compare/trims/route.ts", "utf8");
check("the picker route reads the lightweight compare-picker loader",
  pickerRoute.includes("getCanonicalCompareTrimOptions"), true);
check("the picker route does not fall back to the full rich-payload helper",
  pickerRoute.includes("getCanonicalCompareTrims("), false);

const compareRoute = fs2.readFileSync("app/api/tools/compare/route.ts", "utf8");
check("an actual comparison fetches rich data only for the requested trim IDs",
  compareRoute.includes("getCanonicalCompareTrimsByIds"), true);
check("the rich lookup does not fall back to the full-catalogue helper",
  compareRoute.includes("getCanonicalCompareTrims("), false);
check("the rich query constrains by the requested canonical IDs, not a table scan",
  compareCanonicalData.includes('.in("canonical_id", requested)'), true);
check("requested IDs are deduplicated and capped at four",
  compareCanonicalData.includes("new Set(ids.filter(Boolean))") && compareCanonicalData.includes(".slice(0, 4)"), true);
check("rich rows are returned in the caller's requested order, not database row order",
  compareCanonicalData.includes("requested.map((id) => byId.get(id))"), true);
check("missing/invalid selections surface as missing_selection, never a shifted comparison",
  compareRoute.includes("missing_selection: requestedIds.length !== selected.length"), true);

const picker = fs2.readFileSync("app/compare/page.tsx", "utf8");
check("the picker is model then trim, not one list of every trim",
  picker.includes("groupByModel"), true);
check("choosing a car does not require an account",
  picker.includes("compareSignIn") && !picker.includes('ต้องเข้าสู่ระบบก่อนเทียบรถ'), true);
check("a selection survives being sent to the login page",
  picker.includes("/member/login?next="), true);

console.log("\nfree compare — origin/import are already live, under production_type/production_country");
check("origin_country reuses the existing production_country row, not a second field",
  keys.includes("production_country") && keys.filter((k) => k.includes("origin")).length, 0);
check("import_type reuses the existing production_type row, not a second field",
  keys.includes("production_type") && keys.filter((k) => k.includes("import_type")).length, 0);

console.log("\nfree compare — cab type is a pickup-only concept, never shown against another body type");
const pickupA: FreeCompareTrim = { id: "p1", body_type: "PICKUP", cab_type: "DOUBLE_CAB" };
const pickupB: FreeCompareTrim = { id: "p2", body_type: "PICKUP", cab_type: "SMART_CAB" };
const sedan: FreeCompareTrim = { id: "s1", body_type: "SEDAN", cab_type: "NOT_APPLICABLE" };
check("a pickup's cab type reads through", compareValue(pickupA, "cab_type"), "DOUBLE_CAB");
check("a sedan's cab type is never shown, even if the column carries a stray value",
  compareValue({ ...sedan, cab_type: "DOUBLE_CAB" }, "cab_type"), null);
check("a pickup's own NOT_APPLICABLE cab type never prints as a value",
  compareValue({ id: "p3", body_type: "PICKUP", cab_type: "NOT_APPLICABLE" }, "cab_type"), null);
check("comparing two pickups shows the row", visibleCompareGroups([pickupA, pickupB])
  .flatMap((g) => g.rows.map((r) => r.key)).includes("cab_type"), true);
check("comparing two sedans hides the row entirely -- never shown against another body type",
  visibleCompareGroups([sedan, { ...sedan, id: "s2" }])
    .flatMap((g) => g.rows.map((r) => r.key)).includes("cab_type"), false);
check("a pickup next to a sedan still shows the row (the sedan's cell is the ordinary missing dash)",
  visibleCompareGroups([pickupA, sedan]).flatMap((g) => g.rows.map((r) => r.key)).includes("cab_type"), true);

console.log("\nfree compare — retail_status and launch date are header metadata, never a spec row");
check("retail_status is not a comparable row key", keys.includes("retail_status"), false);
check("launch_year is not a comparable row key", keys.includes("launch_year"), false);

console.log("\nfree compare — nothing internal-only reaches the public tool");
for (const forbidden of ["registration_type", "market_scope", "nameplate", "variant_id", "price_min_thb", "price_max_thb"]) {
  check(`${forbidden} is never a compare row key`, keys.includes(forbidden), false);
}
const routeSource = fs2.readFileSync("app/api/tools/compare/route.ts", "utf8");
for (const forbidden of ["registration_type", "market_scope", "nameplate", "price_min_thb", "price_max_thb"]) {
  check(`${forbidden} does not appear in the compare API route at all`, routeSource.includes(forbidden), false);
}
check("price comes from the real MarketTrim/Price Ledger column (price_baht), not an analytical Variant range",
  canonicalData.includes("price_baht: list?.amount_thb") && !canonicalData.includes("price_min_thb") && !canonicalData.includes("price_max_thb"), true);

console.log("\nfree compare — retail_status/launch wiring reuses existing canonical fields, no new query");
const canonicalData2 = fs2.readFileSync("lib/canonical-data.ts", "utf8");
check("cab_type is read from the already-fetched model payload, not a new column",
  canonicalData2.includes("cab_type: model?.cab_type"), true);
check("retail_status reuses trim.status -- the field trimRow() already sets -- under its Compare-facing name",
  canonicalData2.includes("retail_status: trim.status"), true);
check("launch_year/launch_quarter are read from the already-fetched model payload, not a new query",
  canonicalData2.includes("launch_year: model?.launch_year") && canonicalData2.includes("launch_quarter: model?.launch_quarter"), true);
check("the route surfaces retail_status/launch on the header projection, not as a comparable row",
  routeSource.includes("retail_status: trim.retail_status") && routeSource.includes("launch_year: trim.launch_year"), true);
const comparePage2 = fs2.readFileSync("app/compare/page.tsx", "utf8");
check("the page renders a retail-status badge in the column header",
  comparePage2.includes("compareStatusBadge"), true);
check("the page renders launch date as header metadata under the trim name, not a table row",
  comparePage2.includes("compareLaunchMeta"), true);
check("cab type reuses the canonical Thai label map (no second translation invented)",
  comparePage2.includes("cabLabel"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall free compare checks passed");
process.exit(failed ? 1 : 0);
