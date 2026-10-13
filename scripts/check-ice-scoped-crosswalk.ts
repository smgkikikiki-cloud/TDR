import assert from "node:assert/strict";
import {
  IceScopedResolver, normalizeIceRegType, primaryCanonicalForScopedGroup,
  scopedCoverage, scopedDimensionTotals,
  type OwnerScopedDecision,
} from "../lib/ice-scoped-crosswalk.ts";
import type { IceRegTrendRow, IceCrosswalkLink, VehicleModelDim } from "../lib/ice-market-engine.ts";

function decision(
  group: string, scope: string, status: OwnerScopedDecision["status"],
  target: string | null = null,
): OwnerScopedDecision {
  return {
    model_group_id: group, reg_type_scope: scope, status,
    canonical_model_id: target, decision_ref: "frozen-owner-evidence",
    master_version: "7.0",
  };
}
function fact(group: string, scope: string, n: number, province = "Bangkok"): IceRegTrendRow {
  return {
    period: "2569-09", province, reg_type: scope,
    brand: "Toyota", model_group_id: group, model_name: group, reg_count: n,
  };
}
function resolver(
  owner: OwnerScopedDecision[],
  legacy: IceCrosswalkLink[] = [],
  materialized: string[] = [],
  scopedOnly: string[] = [],
): IceScopedResolver {
  return new IceScopedResolver(owner, legacy, materialized, "7.0", scopedOnly);
}

assert.equal(normalizeIceRegType("RY2"), "รย.2");
assert.equal(normalizeIceRegType("รย.3"), "รย.3");
assert.throws(() => normalizeIceRegType("3"));

const many = resolver([
  decision("KUN15R", "ALL", "APPROVED", "toyota.vigo"),
  decision("TGN16R", "ALL", "APPROVED", "toyota.vigo"),
], [], ["toyota.vigo"]);
const manyFacts = many.resolveRows([
  fact("KUN15R", "รย.1", 50), fact("TGN16R", "รย.1", 45, "Chonburi"),
]);
assert.deepEqual(manyFacts.map(row => row.canonical_model_id), ["toyota.vigo", "toyota.vigo"]);
assert.equal(scopedCoverage(manyFacts).covered_units, 95);
assert.equal(scopedCoverage(manyFacts).fixed_denominator, 95);

const pickup = resolver([
  decision("TRITON", "ALL", "PENDING"),
  decision("TRITON", "RY1", "APPROVED", "triton.double"),
  decision("TRITON", "RY2", "APPROVED", "triton.double"),
  decision("TRITON", "RY3", "APPROVED", "triton.cab"),
], [], ["triton.double", "triton.cab"], ["TRITON"]);
const pickupFacts = pickup.resolveRows([
  fact("TRITON", "รย.1", 60), fact("TRITON", "รย.2", 2),
  fact("TRITON", "รย.3", 40), fact("TRITON", "รย.9", 3),
]);
assert.deepEqual(pickupFacts.map(row => row.canonical_model_id),
  ["triton.double", "triton.double", "triton.cab", null]);
assert.equal(pickupFacts[3].mapping_status, "SCOPED_CLASS_UNRESOLVED");
assert.equal(scopedCoverage(pickupFacts).covered_units, 102);
assert.equal(scopedCoverage(pickupFacts).fixed_denominator, 105);
assert.equal(primaryCanonicalForScopedGroup(pickupFacts, "TRITON"), null);

const dim: VehicleModelDim[] = [
  { canonical_id: "triton.double", segment: "Pickup", body_type: "Double Cab" },
  { canonical_id: "triton.cab", segment: "Pickup", body_type: "Other Cab" },
];
const body = scopedDimensionTotals(pickupFacts, dim, "body_type");
assert.equal(body.get("Double Cab"), 62);
assert.equal(body.get("Other Cab"), 40);
assert.equal(body.get("ไม่ระบุ"), 3);
assert.equal([...body.values()].reduce((a, b) => a + b, 0), 105);

const legacy: IceCrosswalkLink[] = [
  { model_group_id: "HONDA-E", canonical_model_id: "honda.en2", status: "AUTO" },
  { model_group_id: "JAZZ", canonical_model_id: "honda.jazz", status: "AUTO" },
  { model_group_id: "PROPOSAL", canonical_model_id: "honda.wrong", status: "PROPOSED" },
];
const mixed = resolver([
  decision("HONDA-E", "ALL", "EXCLUDED"),
  decision("SERENA", "ALL", "APPROVED", "nissan.serena"),
], legacy, ["honda.en2", "honda.jazz", "honda.wrong", "nissan.serena"]);
const mixedFacts = mixed.resolveRows([
  fact("HONDA-E", "RY1", 10), fact("JAZZ", "RY1", 20),
  fact("PROPOSAL", "RY1", 70), fact("SERENA", "RY1", 30),
]);
assert.deepEqual(mixedFacts.map(x => x.mapping_status),
  ["OWNER_EXCLUDED", "LEGACY_ACTIVE", "UNMATCHED", "OWNER_APPROVED"]);
assert.deepEqual(scopedCoverage(mixedFacts), {
  fixed_denominator: 130, owner_excluded_units: 10,
  adjusted_denominator: 120, covered_units: 50,
  fixed_denominator_coverage_pct: 100 * 50 / 130,
});

const missing = resolver([decision("NEW", "ALL", "APPROVED", "hino.new")]);
assert.equal(missing.resolve(fact("NEW", "RY1", 50)).mapping_status, "PENDING_MATERIALIZATION");
assert.throws(() => resolver([
  decision("g", "RY1", "APPROVED", "a"),
  decision("g", "รย.1", "APPROVED", "b"),
]), /Duplicate owner scope/);
assert.throws(() => new IceScopedResolver([
  { ...decision("g", "ALL", "APPROVED", "a"), master_version: "6.0" },
], [], ["a"], "7.0"), /stale/);

console.log("R6 v2 scoped reader: owner precedence, RY class splits, many-to-one, "
  + "no double-count, fixed denominator, metadata ambiguity and exclusions PASS");
