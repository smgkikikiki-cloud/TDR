import assert from "node:assert/strict";
import { runR7Checks, type R7Input } from "../lib/ice-r7-acceptance.ts";

const row = (group: string, regType: string, n: number, period = "2569-09", province = "Bangkok") => ({
  period, province, reg_type: regType, brand: "TEST", model_group_id: group, model_name: group, reg_count: n,
});
const dec = (group: string, scope: string, status: any, target: string | null) => ({
  model_group_id: group, reg_type_scope: scope, status, canonical_model_id: target, decision_ref: "owner:x", master_version: "7.0",
});
const panels = ["rim_province", "tyre_province"].map(panel_id => ({
  panel_id, period_from: "2567-01", period_to: "2569-09", access: { view: ["paid"] }, free_scope: null, confirmed_by: ["owner"],
}));
const base = (): R7Input => ({
  masterVersion: "7.0", period: "2569-09", panels,
  trend: [row("a", "รย.1", 100), row("b", "รย.1", 50), row("c", "รย.1", 10), row("a", "รย.1", 70, "2569-08")],
  province: [{ period: "2569-09", province: "Bangkok", reg_type: "รย.1", brand: "TEST", fuel_group: "ICE", reg_count: 160 } as any],
  powertrain: [{ period: "2569-09", province: "Bangkok", reg_type: "รย.1", brand: "TEST", model_group_id: "a", model_name: "a", fuel_group: "ICE", reg_est: 100, reg_min: null, reg_max: null, certainty: "exact" } as any],
  tyreCoverage: [{ period: "2569-09", province: "Bangkok", reg_type: "รย.1", brand: "TEST", reg_total: 160, reg_tyre_known: 80 } as any],
  decisions: [dec("a", "ALL", "APPROVED", "t.a"), dec("b", "ALL", "EXCLUDED", null)],
  vehicleModels: [{ canonical_id: "t.a", segment: "SUV", body_type: "SUV" }],
  redirects: [{ old_model_group_id: "x", new_model_group_id: "a" }],
  knownGroupIds: ["a", "b", "c"],
});
const byId = (checks: ReturnType<typeof runR7Checks>, id: string) => checks.find(c => c.id === id)!;

// healthy data: c is undecided but stays visible, so nothing is dropped
let checks = runR7Checks(base());
assert.equal(checks.filter(c => c.status === "FAIL").length, 0, JSON.stringify(checks.filter(c => c.status === "FAIL")));
assert.equal(byId(checks, "R7-1").status, "PASS");
assert.deepEqual((byId(checks, "R7-4").detail as any).segment.unspecified_units, 60); // b excluded + c unmapped are counted as ไม่ระบุ, not hidden

// Ice's two panels disagree -> FAIL
const off = base(); off.province = [{ ...(off.province[0] as any), reg_count: 159 }];
assert.equal(byId(runR7Checks(off), "R7-3a").status, "FAIL");

// a stale decision version stops everything with a clear failure
const stale = base(); stale.decisions = [{ ...stale.decisions[0], master_version: "6.9" }];
checks = runR7Checks(stale);
assert.equal(checks.length, 1); assert.equal(checks[0].status, "FAIL");

// redirect cycle -> FAIL
const loop = base(); loop.redirects = [{ old_model_group_id: "a", new_model_group_id: "b" }, { old_model_group_id: "b", new_model_group_id: "a" }];
assert.equal(byId(runR7Checks(loop), "R7-7").status, "FAIL");

// powertrain disagreeing with reg_trend -> FAIL
const pt = base(); (pt.powertrain[0] as any).reg_est = 90;
assert.equal(byId(runR7Checks(pt), "R7-5").status, "FAIL");

// missing panel metadata is reported, never guessed
const nopanel = base(); nopanel.panels = [];
assert.equal(byId(runR7Checks(nopanel), "R7-6").status, "FAIL");
console.log("ice-r7-acceptance checks ok");
