import { readFileSync } from "node:fs";
import {
  FREE_COMPARE_GROUPS,
  compareValue,
  rowIsDifferent,
  visibleCompareGroups,
  type FreeCompareTrim,
} from "../lib/free-compare.ts";
import { factsByTrim, specCell } from "../lib/compare-facts.ts";

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

console.log("\ncompare workspace — registry contract");
const registryPath = new URL(
  "../automotive/vehicle_master/vehreg/data/2026/product/comparable_specs/registry.json",
  import.meta.url,
);
const workspacePath = new URL("../lib/compare-workspace.ts", import.meta.url);
const registry = JSON.parse(readFileSync(registryPath, "utf8"));
const workspaceSource = readFileSync(workspacePath, "utf8");
const registered = new Set<string>(registry.fields.map((field: { key: string }) => field.key));
const workspaceSpecKeys = [...new Set(
  [...workspaceSource.matchAll(/\bspec\("([^"]+)"/g)].map((match) => match[1]),
)].sort();
check(
  "every Compare spec key exists in canonical registry",
  workspaceSpecKeys.filter((key) => !registered.has(key)),
  [],
);
check(
  "public workspace does not expose tyre/wheel fitment facts",
  workspaceSpecKeys.some((key) => key.startsWith("fitment.")),
  false,
);

console.log("\ncompare workspace — fail-closed facts");
const facts = factsByTrim([
  {
    trim_id: "a", field_key: "safety.abs", value_state: "KNOWN", value: true,
    verification_status: null,
  },
  {
    trim_id: "a", field_key: "safety.aeb", value_state: "KNOWN", value: true,
    verification_status: "PROVISIONAL",
  },
  {
    trim_id: "a", field_key: "safety.ebd", value_state: "KNOWN", value: false,
    verification_status: "VERIFIED", effective_from: "2026-01-01",
  },
]);
check("missing verification status is rejected", facts.get("a")?.has("safety.abs") ?? false, false);
check("provisional fact is rejected", facts.get("a")?.has("safety.aeb") ?? false, false);
check("verified fact is retained", facts.get("a")?.has("safety.ebd") ?? false, true);
check("verified false means ไม่มี", specCell(facts.get("a")?.get("safety.ebd")).display, "ไม่มี");
check("missing fact remains unknown, not false", specCell(undefined).display, null);

console.log(failed ? `\n${failed} check(s) failed` : "\nall free compare checks passed");
process.exit(failed ? 1 : 0);
