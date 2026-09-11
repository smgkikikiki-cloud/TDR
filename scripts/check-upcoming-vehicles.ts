import { readFileSync } from "node:fs";
import {
  launchWindowLabel,
  validateUpcomingDataset,
  type UpcomingDataset,
} from "../lib/upcoming-schema.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const path = new URL("../data/upcoming/vehicles.json", import.meta.url);
const dataset = JSON.parse(readFileSync(path, "utf8"));

console.log("upcoming vehicles — canonical registry");
check("repository dataset validates", validateUpcomingDataset(dataset), []);

const sample: UpcomingDataset = {
  schema_version: 1,
  vehicles: [{
    id: "demo.vehicle",
    slug: "demo-vehicle",
    market: "TH",
    brand: "Demo",
    working_name: "Vehicle",
    status: "SCHEDULED",
    visibility: "PUBLIC",
    launch_window: { start: "2027-01-01", end: "2027-03-31", precision: "QUARTER" },
    body_type: "CROSSOVER",
    powertrains: ["HEV"],
    facts: [{ field_key: "powertrain.type", label: "Powertrain", value: "HEV", scope: "THAI_MARKET", certainty: "CONFIRMED" }],
    timeline: [{ date: "2026-09-11", title: "Thai launch window announced", kind: "OFFICIAL_THAI", source_label: "OEM" }],
    first_seen: "2026-09-11",
    updated_at: "2026-09-11",
  }],
};
check("valid scheduled sample", validateUpcomingDataset(sample), []);
check("quarter display stays broad", launchWindowLabel(sample.vehicles[0].launch_window), "Q1 2027");

console.log("\nupcoming vehicles — fail closed semantics");
const noDate = structuredClone(sample);
noDate.vehicles[0].launch_window = { start: null, end: null, precision: "UNKNOWN" };
check("scheduled vehicle cannot have unknown timing", validateUpcomingDataset(noDate).some((p) => p.includes("SCHEDULED requires")), true);

const launched = structuredClone(sample);
launched.vehicles[0].status = "LAUNCHED";
check("launched record must link to canonical model", validateUpcomingDataset(launched).some((p) => p.includes("LAUNCHED requires linked_model_id")), true);

const inventedDate = structuredClone(sample);
inventedDate.vehicles[0].launch_window = { start: "2027-01-15", end: null, precision: "UNKNOWN" };
check("unknown precision cannot smuggle an exact date", validateUpcomingDataset(inventedDate).some((p) => p.includes("UNKNOWN launch window cannot carry dates")), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall upcoming vehicle checks passed");
process.exit(failed ? 1 : 0);
