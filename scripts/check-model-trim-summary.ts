import assert from "node:assert/strict";
import { trimSummarySpecs } from "../lib/model-trim-summary.ts";
import type { CompareSpecField, FreeCompareTrim } from "../lib/free-compare.ts";

const fields: CompareSpecField[] = [
  {
    key: "safety.airbag_count",
    group: "safety",
    labelTh: "จำนวนถุงลมนิรภัย",
    canonicalUnit: "airbag",
    displayPrecision: 0,
    comparisonQualifiers: [],
  },
];

const trim: FreeCompareTrim = {
  id: "aion.aion_ut.gen1.trim.400_standard_range_bev",
  name: "420 Standard",
  powertrain: "BEV",
  drivetrain: "FWD",
  battery_kwh: 50.27,
  seats: 5,
  length_mm: 4270,
  width_mm: 1850,
  height_mm: 1575,
  wheelbase_mm: 2750,
  comparable_specs: [
    {
      field_key: "safety.airbag_count",
      value_state: "KNOWN",
      value: 6,
      unit: "airbag",
      qualifiers: {},
    },
  ],
};

const summary = trimSummarySpecs(trim, fields, 6);
assert.deepEqual(summary.map((row) => row.key), [
  "drivetrain",
  "battery_kwh",
  "spec:safety.airbag_count",
  "seats",
]);
assert.equal(summary.find((row) => row.key === "spec:safety.airbag_count")?.value, "6 airbag");
assert.equal(summary.some((row) => ["length_mm", "width_mm", "height_mm", "wheelbase_mm"].includes(row.key)), false);
assert.equal(trimSummarySpecs(trim, fields, 2).length, 2);
assert.deepEqual(trimSummarySpecs(trim, fields, 0), []);

console.log("model trim summary checks passed");
