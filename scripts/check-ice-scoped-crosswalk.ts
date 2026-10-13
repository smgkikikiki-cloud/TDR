/**
 * Independent deterministic R6 V2 reader contract tests; NO database/network.
 * Run: node --experimental-strip-types scripts/check-ice-scoped-crosswalk.ts
 */
import assert from "node:assert/strict";
import {
  aggregateScopedRegistrations,
  compileScopedCrosswalk,
  normalizedIceRegType,
  type ScopedCrosswalkLink,
} from "../lib/ice-scoped-crosswalk-contract.ts";

const version = "7.0";
const record = (
  model_group_id: string, reg_type: string | null, canonical_model_id: string | null,
  status: ScopedCrosswalkLink["status"] = "APPROVED",
): ScopedCrosswalkLink => ({
  master_version: version, model_group_id, reg_type, canonical_model_id, status,
});

assert.equal(normalizedIceRegType("RY1"), "รย.1");
assert.equal(normalizedIceRegType("ry2"), "รย.2");
assert.equal(normalizedIceRegType("รย.3"), "รย.3");

const links: ScopedCrosswalkLink[] = [
  // Two *separate Ice groups* are one owner-approved canonical model.
  record("toyota-vigo-kun15", null, "toyota.hilux_vigo"),
  record("toyota-vigo-kun35", null, "toyota.hilux_vigo"),
  record("bmw-i8-rhd", null, "bmw.i8"),
  record("bmw-i8-roadster", null, "bmw.i8"),

  // RY1/RY3 within ONE Ice group lead to DIFFERENT models by owner rule.
  record("mitsubishi-triton", "รย.1", "mitsubishi.triton_double_cab"),
  record("mitsubishi-triton", "RY3", "mitsubishi.triton_cab"),
  // Group-only legacy row must NOT leak into an unapproved RY2 class.
  record("mitsubishi-triton", null, "mitsubishi.triton_double_cab", "AUTO"),
  record("toyota-travo", "RY1", "toyota.hilux_travo_double_cab"),
  record("toyota-travo", "RY2", "toyota.hilux_travo_double_cab"),
  record("toyota-travo", "RY3", "toyota.hilux_travo_cab"),

  // PROPOSED and REJECTED must never be served as confirmed.
  record("nissan-pending", null, "nissan.serena", "PROPOSED"),
  record("byd-rejected", null, "byd.atto1", "REJECTED"),

  // A source grain may NOT fan out to two active canonical identities.
  record("bad-collision", "RY1", "a.first"),
  record("bad-collision", "รย.1", "a.second", "AUTO"),

  // Owner EXCLUDE must preserve the registration units in gross accounting.
  record("excluded-legacy", null, null, "EXCLUDED"),

  // A conflicting exclude + active map is an explicit ambiguous error state.
  record("exclude-conflict", "RY1", "b.active"),
  record("exclude-conflict", "RY1", null, "EXCLUDED"),

  // Version mismatch cannot silently authorize a mapping for a new release.
  { master_version: "6.0", model_group_id: "wrong-version", reg_type: null,
    canonical_model_id: "wrong.legacy", status: "APPROVED" },
];

const resolve = compileScopedCrosswalk(links, version);
assert.deepEqual(resolve("toyota-vigo-kun15", "รย.3"), {
  kind: "LINKED", canonical_model_id: "toyota.hilux_vigo", scope: "LEGACY",
});
assert.deepEqual(resolve("mitsubishi-triton", "รย.1"), {
  kind: "LINKED", canonical_model_id: "mitsubishi.triton_double_cab", scope: "SCOPED",
});
assert.deepEqual(resolve("mitsubishi-triton", "RY3"), {
  kind: "LINKED", canonical_model_id: "mitsubishi.triton_cab", scope: "SCOPED",
});
assert.deepEqual(resolve("mitsubishi-triton", "RY2"), {
  kind: "UNMAPPED", canonical_model_id: null, scope: "SCOPED",
});
assert.deepEqual(resolve("toyota-travo", "RY2"), {
  kind: "LINKED", canonical_model_id: "toyota.hilux_travo_double_cab", scope: "SCOPED",
});
assert.equal(resolve("nissan-pending", "RY1").kind, "UNMAPPED");
assert.equal(resolve("byd-rejected", "RY1").kind, "UNMAPPED");
assert.equal(resolve("bad-collision", "RY1").kind, "AMBIGUOUS");
assert.equal(resolve("excluded-legacy", "RY3").kind, "EXCLUDED");
assert.equal(resolve("exclude-conflict", "RY1").kind, "AMBIGUOUS");
assert.equal(resolve("wrong-version", "RY1").kind, "UNMAPPED");

const totals = aggregateScopedRegistrations([
  { model_group_id: "toyota-vigo-kun15", reg_type: "RY3", reg_count: 10 },
  { model_group_id: "toyota-vigo-kun35", reg_type: "RY3", reg_count: 20 },
  { model_group_id: "bmw-i8-rhd", reg_type: "RY1", reg_count: 4 },
  { model_group_id: "bmw-i8-roadster", reg_type: "RY1", reg_count: 6 },
  { model_group_id: "mitsubishi-triton", reg_type: "RY1", reg_count: 100 },
  { model_group_id: "mitsubishi-triton", reg_type: "RY3", reg_count: 80 },
  { model_group_id: "mitsubishi-triton", reg_type: "RY2", reg_count: 5 },
  { model_group_id: "toyota-travo", reg_type: "RY2", reg_count: 40 },
  { model_group_id: "nissan-pending", reg_type: "RY1", reg_count: 3 },
  { model_group_id: "byd-rejected", reg_type: "RY1", reg_count: 2 },
  { model_group_id: "bad-collision", reg_type: "RY1", reg_count: 8 },
  { model_group_id: "excluded-legacy", reg_type: "RY1", reg_count: 9 },
  { model_group_id: "exclude-conflict", reg_type: "RY1", reg_count: 7 },
  { model_group_id: "wrong-version", reg_type: "RY1", reg_count: 11 },
], resolve);
assert.deepEqual(totals, {
  raw_units: 305,
  linked_units: 260,
  unresolved_units: 21,
  excluded_units: 9,
  ambiguous_units: 15,
  units_by_canonical: {
    "toyota.hilux_vigo": 30,
    "bmw.i8": 10,
    "mitsubishi.triton_double_cab": 100,
    "mitsubishi.triton_cab": 80,
    "toyota.hilux_travo_double_cab": 40,
  },
});
assert.equal(
  totals.raw_units,
  totals.linked_units + totals.unresolved_units +
  totals.excluded_units + totals.ambiguous_units,
);
assert.throws(
  () => aggregateScopedRegistrations([
    { model_group_id: "mitsubishi-triton", reg_type: "RY1", reg_count: -3 },
  ], resolve),
  /invalid registration count/,
);
console.log("R6 V2 scoped crosswalk offline contract PASS: shared identities, pickup classes, no fanout, no unit loss.");
