/**
 * Executable October 2026 PDI OEM pilot. These are SOURCE-BACKED numbers, not
 * synthetic fixture numbers and NOT a publishable national PDI. Both examples
 * are mapped to the reviewed Vehicle Master current retail trim sets.
 *
 * npm run pdi:pilot               offline pinned source/release calculation
 * npm run pdi:pilot -- --verify-live  also asserts live master parity (read-only)
 */
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {calculatePdi,type PdiModel,type PdiTrim,type PdiResult} from "../lib/pdi-engine.ts";
import {classifyPdiUniverse,PDI_UNIVERSE_POLICY} from "../lib/pdi-universe-policy.ts";
type PilotEvidence = {
 contract:string;status:string;asOf:string;observedAt:string;effectiveFrom:string;effectiveTo:string;
 sourceUrl:string;sourceClass:string;territory:string;
 vehicleMaster:{seedReleaseId:string;seedAsOf:string;modelId:string;reviewedRetailSetAt:string};
 trims:{trimId:string;powertrain:string;msrpThb:number;cashDiscountThb:number;advertisedNetPriceThb:number}[];
};
function load(file:string):PilotEvidence {
  const data=JSON.parse(readFileSync(new URL("../data/pdi/"+file,import.meta.url),"utf8")) as PilotEvidence;
  assert.equal(data.status,"ANALYST_VERIFIED_PILOT_NOT_HEADLINE");
  assert.equal(data.sourceClass,"OFFICIAL_OEM");
  assert.equal(data.territory,"NATIONWIDE");
  assert.ok(data.sourceUrl.startsWith("https://www.changan.co.th/"));
  assert.ok(data.effectiveFrom<=data.asOf && data.asOf<=data.effectiveTo);
  assert.ok(data.observedAt<=data.asOf);
  assert.ok(data.trims.length>0);
  for(const t of data.trims) {
    assert.ok(Number.isSafeInteger(t.msrpThb)&&t.msrpThb>0);
    assert.ok(Number.isSafeInteger(t.cashDiscountThb)&&t.cashDiscountThb>=0);
    assert.equal(t.msrpThb-t.cashDiscountThb,t.advertisedNetPriceThb);
  }
  return data;
}
const evidence=[load("pilot-2026-10-e07.json"),load("pilot-2026-10-s07.json")];
assert.equal(new Set(evidence.map(e=>e.vehicleMaster.modelId)).size,evidence.length);
assert.equal(new Set(evidence.map(e=>e.vehicleMaster.seedReleaseId)).size,1);
assert.equal(new Set(evidence.map(e=>e.asOf)).size,1);
function build(e:PilotEvidence):PdiModel {
  const admission=classifyPdiUniverse({
    modelId:e.vehicleMaster.modelId,brandOrigin:"CN",bodyType:"CROSSOVER",currentRetail:true,marketPosition:"Mass"
  });
  assert.equal(admission.bucket,"PASSENGER_HEADLINE");
  const trims:PdiTrim[]=e.trims.map(t=>({
    trimId:t.trimId,powertrain:t.powertrain,currentRetail:true,
    msrp:{amountThb:t.msrpThb,sourceId:e.contract+":MSRP:"+t.trimId,
      sourceRef:e.sourceUrl,observedAt:e.observedAt,effectiveFrom:e.effectiveFrom,
      effectiveTo:e.effectiveTo,verified:true},
    cashEvidence:[{kind:"CASH_BUNDLE",amountThb:t.cashDiscountThb,
      retailScope:"NATIONWIDE",eligibility:"GENERAL",stackingVerified:false,
      componentIds:[e.contract+":CASH:"+t.trimId],
      sourceId:e.contract+":CASH:"+t.trimId,sourceRef:e.sourceUrl,
      observedAt:e.observedAt,effectiveFrom:e.effectiveFrom,
      effectiveTo:e.effectiveTo,verified:true}]
  }));
  return {modelId:e.vehicleMaster.modelId,brandOrigin:"CN",currentRetail:true,
    japaneseAdmission:"APPROVED",retailSetBasis:"REVIEWED",trims};
}
const output=calculatePdi({asOf:evidence[0].asOf,sourceSnapshot:evidence[0].vehicleMaster.seedReleaseId,
  universeVersion:PDI_UNIVERSE_POLICY+":SAMPLE-ONLY",models:evidence.map(build)});
assert.equal(output.scoredModelCount,2);
assert.equal(output.eligibleModelCount,2);
assert.equal(output.eligibleTrimCount,3);
assert.equal(output.verifiedTrimCount,3);
assert.equal(output.modelCoveragePct,100); // WITHIN SELECTED PILOT BASKET ONLY
assert.equal(output.publishableHeadlinePdiPct,null);
assert.equal(output.publicationStatus,"RESEARCH_ONLY");
const e07=output.modelResults.find(r=>r.modelId==="deepal.deepal_e07");
const s07=output.modelResults.find(r=>r.modelId==="deepal.deepal_s07");
assert.ok(e07 && s07);
assert.equal(e07.medianMsrpThb,1_899_000);
assert.equal(e07.medianDiscountThb,75_000);
assert.equal(e07.medianNetOfferPriceThb,1_824_000);
assert.ok(Math.abs((e07.pdiPct??0)-100*75_000/1_899_000)<1e-10);
assert.equal(s07.medianMsrpThb,1_219_000);
assert.equal(s07.medianDiscountThb,120_000);
assert.equal(s07.medianNetOfferPriceThb,1_099_000);
assert.ok(Math.abs((s07.pdiPct??0)-100*120_000/1_219_000)<1e-10);
assert.ok(Math.abs((output.researchMeanPdiPct??0)-((e07.pdiPct??0)+(s07.pdiPct??0))/2)<1e-10);
async function verifyLive() {
  const {adminDb}=await import("../lib/supabase.ts");
  const db=adminDb();
  assert.ok(db,"Server-only Supabase secret missing for --verify-live");
  const {data:state,error:se}=await db.from("vehicle_master_state").select("seed_release_id,seed_as_of")
    .eq("scope","vehicle_master").single();
  if(se)throw se;
  assert.equal(state?.seed_release_id,evidence[0].vehicleMaster.seedReleaseId,
    "Vehicle Master release changed; re-review pilot against new release before using any number");
  assert.equal(state?.seed_as_of,evidence[0].vehicleMaster.seedAsOf);
  for(const e of evidence) {
    const {data:rs,error:re}: {data:{trim_ids:string[];reviewed_at:string}|null;error:unknown}=await db.from("vehicle_current_retail_sets")
      .select("trim_ids,reviewed_at").eq("model_id",e.vehicleMaster.modelId).single();
    if(re)throw re;
    assert.deepEqual((rs?.trim_ids||[]).slice().sort(),e.trims.map(t=>t.trimId).sort(),
      "Changed current trim membership; re-review OEM pilot");
    assert.equal(rs?.reviewed_at,e.vehicleMaster.reviewedRetailSetAt);
    const {data:trims,error:te}: {data:Array<{canonical_id:string;status:string;powertrain:string;deleted_at:string|null}>|null;error:unknown}=await db.from("vehicle_trims")
      .select("canonical_id,status,powertrain,deleted_at").eq("model_id",e.vehicleMaster.modelId);
    if(te)throw te;
    for(const t of e.trims){
      const found:{canonical_id:string;status:string;powertrain:string;deleted_at:string|null}|undefined=(trims||[]).find(row=>row.canonical_id===t.trimId);
      assert.ok(found && found.status==="CURRENT" && !found.deleted_at);
      assert.equal(found.powertrain,t.powertrain);
    }
    const {data:prices,error:pe}: {data:Array<{trim_id:string;amount_thb:number|string;price_type:string;retracted_at:string|null}>|null;error:unknown}=await db.from("vehicle_price_ledger")
      .select("trim_id,amount_thb,price_type,retracted_at")
      .in("trim_id",e.trims.map(t=>t.trimId)).eq("price_type","LIST_PRICE");
    if(pe)throw pe;
    for(const t of e.trims)assert.ok((prices||[]).some(row=>
      row.trim_id===t.trimId&&Number(row.amount_thb)===t.msrpThb&&!row.retracted_at),
      "Vehicle Master list price drift; re-review");
  }
}
if(process.argv.includes("--verify-live"))await verifyLive();
const report={
  title:"PDI RESEARCH PILOT — NOT THAILAND NATIONAL INDEX",
  asOf:output.asOf,methodology:output.methodologyVersion,
  universePolicy:PDI_UNIVERSE_POLICY,sourceSnapshot:output.sourceSnapshot,
  coverageScope:"TWO SPECIFICALLY SELECTED, OFFICIALLY EVIDENCED MODELS ONLY",
  index:output.researchMeanPdiPct,
  publicationStatus:output.publicationStatus,
  nationalPdi:null,
  models:output.modelResults.map(r=>({
    modelId:r.modelId,status:r.status,retailTrimCount:r.includedTrimIds.length,
    medianMsrpThb:r.medianMsrpThb,medianCashDiscountThb:r.medianDiscountThb,
    modelPdiPct:r.pdiPct,medianNetOfferPriceThb:r.medianNetOfferPriceThb,
    evidenceUrl:evidence.find(e=>e.vehicleMaster.modelId===r.modelId)?.sourceUrl
  })),
  modelsInPilot:2,scoredModelsInPilot:2,trimsInPilot:3,
  sourceValidation:process.argv.includes("--verify-live")?"LIVE_VEHICLE_MASTER_PARITY_VERIFIED":"PINNED_OFFLINE_EVIDENCE",
  warning:"2/2 coverage is the hand-selected pilot basket, NOT market coverage; prices and promotions require periodic re-verification."
};
console.log(JSON.stringify(report,null,2));
