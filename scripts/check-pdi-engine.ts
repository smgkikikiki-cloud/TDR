import assert from "node:assert/strict";
import {calculatePdi,likeForLikeDeltaPp,type PdiInput,type PdiTrim,type PdiMsrp,type PdiCashBundle} from "../lib/pdi-engine.ts";
const asOf="2026-10-11";
function price(amountThb:number):PdiMsrp {return {amountThb,sourceId:"MSRP-"+amountThb,sourceRef:"official-evidence",observedAt:"2026-10-01",verified:true};}
function cash(amountThb:number, opts:Partial<PdiCashBundle>={}):PdiCashBundle {
  return {kind:"CASH_BUNDLE",amountThb,retailScope:"NATIONWIDE",eligibility:"GENERAL",
    componentIds:["cash"],stackingVerified:false,sourceId:"OFFER-"+amountThb,sourceRef:"official-campaign",
    observedAt:"2026-10-01",verified:true,...opts};
}
function trim(id:string,msrp:number|null,discount:number|null):PdiTrim {
  return {trimId:id,powertrain:"BEV",currentRetail:true,msrp:msrp===null?null:price(msrp),
    cashEvidence:discount===null?[]:discount===0?[{kind:"ZERO_CONFIRMATION",sourceId:"CHECK-"+id,sourceRef:"review-record",observedAt:"2026-10-01",verified:true}]:[cash(discount)]};
}
function model(id:string,trims:PdiTrim[],origin="CN",approval:"APPROVED"|"CANDIDATE"|"REJECTED"="APPROVED") {
  return {modelId:id,brandOrigin:origin,currentRetail:true,japaneseAdmission:approval,trims};
}
function run(models:ReturnType<typeof model>[],overrides:Partial<PdiInput>={}) {
  return calculatePdi({asOf,sourceSnapshot:"vm-main-release",universeVersion:"2026-10",models,...overrides});
}
let r=run([model("threshold",[trim("standard",1_990_000,100_000),trim("premium",2_390_000,200_000)])]);
assert.equal(r.modelResults[0].status,"SCORED");
assert.deepEqual(r.modelResults[0].includedTrimIds,["standard","premium"]);
assert.equal(r.modelResults[0].medianMsrpThb,2_190_000);
r=run([model("excluded",[trim("a",2_000_000,10_000),trim("b",2_200_000,20_000)])]);
assert.equal(r.modelResults[0].status,"NOT_ELIGIBLE");
r=run([model("four",[
  trim("a",1_490_000,100_000),trim("b",1_790_000,0),
  trim("c",2_090_000,200_000),trim("d",2_490_000,300_000)
])]);
assert.equal(r.modelResults[0].medianMsrpThb,1_940_000);
assert.equal(r.modelResults[0].medianDiscountThb,150_000);
assert.ok(Math.abs((r.modelResults[0].pdiPct||0)-7.731958762886598)<1e-10);
assert.equal(r.modelResults[0].medianNetOfferPriceThb,1_840_000); // actual paired net offers
assert.equal(r.modelResults[0].promoTrimBreadth,0.75);
const unknown=run([model("missing",[trim("a",1_000_000,30_000),trim("b",1_500_000,null)])]);
assert.equal(unknown.modelResults[0].status,"PARTIAL");
assert.equal(unknown.eligibleModelCount,1);
assert.equal(unknown.scoredModelCount,0);
assert.equal(unknown.researchMeanPdiPct,null);
assert.equal(unknown.verifiedTrimCount,1);
assert.equal(unknown.publishableHeadlinePdiPct,null);
const combined=run([model("score",[trim("a",1_000_000,100_000)]),model("missing",[trim("b",900_000,null)])]);
assert.equal(combined.eligibleModelCount,2);
assert.equal(combined.scoredModelCount,1);
assert.equal(combined.modelCoveragePct,50);
assert.equal(combined.publicationStatus,"RESEARCH_ONLY");
assert.equal(combined.publishableHeadlinePdiPct,null);
assert.equal(run([model("one",[trim("a",1_000_000,0)])],{publicationApproved:true,approvedMinimumCoveragePct:100}).publicationStatus,"RESEARCH_ONLY");
assert.equal(run([model("one",[trim("a",1_000_000,0)])],{
  publicationApproved:true,methodologyApproved:true,completeUniverseAttested:true,approvedMinimumCoveragePct:100
}).publicationStatus,"PUBLISHABLE");
assert.equal(run([
  model("one",[trim("a",1_000_000,0)]),model("unknown",[trim("b",null,null)])
],{publicationApproved:true,methodologyApproved:true,completeUniverseAttested:true,approvedMinimumCoveragePct:0}).publicationStatus,"RESEARCH_ONLY");
assert.equal(run([model("jp",[trim("a",1_000_000,100_000)],"JP","CANDIDATE")]).modelResults[0].status,"CANDIDATE");
assert.equal(run([model("mixed",[{...trim("a",1_000_000,100_000),powertrain:"ICE"},trim("b",1_500_000,0)])]).modelResults[0].status,"SCOPE_CONFLICT");
const cond=trim("a",1_000_000,null);
cond.cashEvidence=[cash(40000,{eligibility:"STUDENT"}),cash(50000,{eligibility:"FINANCE"})];
assert.equal(run([model("x",[cond])]).modelResults[0].status,"PARTIAL");
const noStack=trim("a",1_000_000,null);
noStack.cashEvidence=[cash(80000),cash(100000,{componentIds:["a","b"],stackingVerified:false})];
assert.equal(run([model("x",[noStack])]).modelResults[0].medianDiscountThb,80000);
noStack.cashEvidence=[cash(80000),cash(100000,{componentIds:["a","b"],stackingVerified:true})];
assert.equal(run([model("x",[noStack])]).modelResults[0].medianDiscountThb,100000);
const alternatives=trim("a",1_000_000,null);
alternatives.cashEvidence=[cash(50000),cash(80000)];
assert.equal(run([model("x",[alternatives])]).modelResults[0].medianDiscountThb,80000);
const dealer=trim("a",1_000_000,null);
dealer.cashEvidence=[cash(90000,{retailScope:"DEALER"})];
assert.equal(run([model("x",[dealer])]).modelResults[0].status,"PARTIAL");
const expired=trim("a",1_000_000,null);
expired.cashEvidence=[cash(50000,{effectiveTo:"2026-10-10"})];
assert.equal(run([model("x",[expired])]).modelResults[0].status,"PARTIAL");
const conflict=trim("a",1_000_000,0);
conflict.competingMsrpClaims=[price(900_000)];
assert.equal(run([model("x",[conflict])]).modelResults[0].status,"CONFLICT");
const tooLarge=trim("a",1_000_000,1_100_000);
assert.equal(run([model("x",[tooLarge])]).modelResults[0].status,"CONFLICT");
const equal=run([model("small",[trim("a",1_000_000,100_000)]),model("big",[
  trim("b1",1_000_000,0),trim("b2",1_000_000,0),trim("b3",1_000_000,0),trim("b4",1_000_000,0)
])]);
assert.equal(equal.researchMeanPdiPct,5);
const prev=run([model("a",[trim("a",1_000_000,100_000)]),model("b",[trim("b",1_000_000,0)])]);
const next=run([model("a",[trim("a",1_000_000,200_000)]),model("new",[trim("c",1_000_000,800_000)])]);
assert.deepEqual(likeForLikeDeltaPp(prev,next),{commonModels:1,deltaPp:10});
assert.throws(()=>run([model("same",[trim("a",1_000_000,0)]),model("same",[trim("b",1_000_000,0)])]),/duplicate/);
console.log("PDI draft deterministic engine acceptance checks: PASS");
