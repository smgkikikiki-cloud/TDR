import {
  FREE_COMPARE_GROUPS,
  compareValue,
  rowIsDifferent,
  visibleCompareGroups,
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

console.log(failed ? `\n${failed} check(s) failed` : "\nall free compare checks passed");
process.exit(failed ? 1 : 0);
