import assert from "node:assert/strict";
import { sliceScopedIceMarket } from "../lib/ice-scoped-market-slices.ts";
import type { IceRegTrendRow, VehicleModelDim, IceModelSliceRow } from "../lib/ice-market-engine.ts";
import type { OwnerScopedDecision } from "../lib/ice-scoped-crosswalk.ts";

const fact = (group: string, regType: string, n: number, province = "Bangkok"): IceRegTrendRow => ({
  period: "2569-09", province, reg_type: regType, brand: "TEST",
  model_group_id: group, model_name: group, reg_count: n,
});
const decisions: OwnerScopedDecision[] = [
  {model_group_id: "pickup",reg_type_scope: "รย.1",status: "APPROVED",canonical_model_id: "vehicle.double",decision_ref: "owner:a",master_version: "7.0"},
  {model_group_id: "pickup",reg_type_scope: "รย.3",status: "APPROVED",canonical_model_id: "vehicle.cab",decision_ref: "owner:b",master_version: "7.0"},
  {model_group_id: "other",reg_type_scope: "ALL",status: "APPROVED",canonical_model_id: "vehicle.double",decision_ref: "owner:c",master_version: "7.0"},
  {model_group_id: "excluded",reg_type_scope: "ALL",status: "EXCLUDED",canonical_model_id: null,decision_ref: "owner:d",master_version: "7.0"},
  {model_group_id: "pending",reg_type_scope: "ALL",status: "PENDING",canonical_model_id: null,decision_ref: "owner:e",master_version: "7.0"},
];
const models: VehicleModelDim[] = [
  {canonical_id:"vehicle.double",segment:"PICKUP",body_type:"DOUBLE_CAB"},
  {canonical_id:"vehicle.cab",segment:"PICKUP",body_type:"CAB"},
];
const facts = [
  fact("pickup","รย.1",100), fact("pickup","รย.3",40),
  fact("other","รย.1",30,"Chonburi"),
  fact("excluded","รย.1",20),fact("pending","รย.1",10),
];
const base = {facts,ownerDecisions:decisions,vehicleModels:models,masterVersion:"7.0",scopedOnlyGroupIds:["pickup"]};
const value = (rows: ReturnType<typeof sliceScopedIceMarket>, key: string) =>
  Number(rows.find(r=>r.entity_key===key)?.registrations ?? 0);
const model = sliceScopedIceMarket({...base,dimension:"model",limit:100}) as IceModelSliceRow[];
assert.deepEqual(model.map(r=>[r.entity_key,Number(r.registrations)]),
  [["pickup",140],["other",30],["excluded",20],["pending",10]]);
assert.equal(model.reduce((n,r)=>n+Number(r.registrations),0),200);
assert.equal(model.find(r=>r.entity_key==="pickup")?.market_total,200);
assert.equal(model.find(r=>r.entity_key==="pickup")?.window_mapped_units,200);
assert.equal(model.find(r=>r.entity_key==="pickup")?.canonical_model_id,null);
assert.equal(model.find(r=>r.entity_key==="other")?.canonical_model_id,"vehicle.double");
assert.equal(model.find(r=>r.entity_key==="excluded")?.canonical_model_id,null);
const body=sliceScopedIceMarket({...base,dimension:"body_type"});
assert.equal(value(body,"DOUBLE_CAB"),130);
assert.equal(value(body,"CAB"),40);
assert.equal(value(body,"ไม่ระบุ"),30);
assert.equal(body[0].window_raw_units,200);
assert.equal(body[0].window_mapped_units,170);
assert.equal(body[0].window_mapping_coverage_pct,85);
assert.equal(body.reduce((n,r)=>n+Number(r.registrations),0),200);
const segment=sliceScopedIceMarket({...base,dimension:"segment"});
assert.equal(value(segment,"PICKUP"),170);
assert.equal(value(segment,"ไม่ระบุ"),30);
const ry1=sliceScopedIceMarket({...base,dimension:"body_type",filters:{registrationTypes:["รย.1"]}});
assert.equal(value(ry1,"DOUBLE_CAB"),130);
assert.equal(value(ry1,"CAB"),0);
assert.equal(value(ry1,"ไม่ระบุ"),30);
assert.equal(ry1.reduce((n,r)=>n+Number(r.registrations),0),160);
const filteredModel = sliceScopedIceMarket({...base,dimension:"model",filters:{registrationTypes:["รย.1"]}}) as IceModelSliceRow[];
assert.equal(filteredModel.find(r=>r.entity_key==="pickup")?.canonical_model_id,null,
  "RY1-only window must not imply that a cross-class split has a group-level canonical ID");
const bkk=sliceScopedIceMarket({...base,dimension:"body_type",filters:{provinces:["Bangkok"]}});
assert.equal(value(bkk,"DOUBLE_CAB"),100);
assert.equal(value(bkk,"CAB"),40);
assert.equal(value(bkk,"ไม่ระบุ"),30);
const missingModel = sliceScopedIceMarket({...base,dimension:"body_type",vehicleModels:[models[0]]});
assert.equal(value(missingModel,"ไม่ระบุ"),70);
const wrongVersion=decisions.map(d=>({...d,master_version:"6.0"}));
assert.throws(()=>sliceScopedIceMarket({...base,dimension:"model",ownerDecisions:wrongVersion}),/stale|source\/version/);
assert.throws(()=>sliceScopedIceMarket({...base,dimension:"model",ownerDecisions:[...decisions,decisions[0]]}),/Duplicate owner scope/);
const absent=sliceScopedIceMarket({...base,dimension:"body_type",ownerDecisions:[],scopedOnlyGroupIds:[]});
assert.equal(value(absent,"ไม่ระบุ"),200);
assert.equal(absent[0].window_mapped_units,0);
console.log("PASS R6 scoped Ice market: many-to-one, RY1/RY3 split, exclusions, missing, filters, zero count changes, version fail-closed");
