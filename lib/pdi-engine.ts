/**
 * TDR PDI v0.5 DRAFT — deterministic, pure calculation only.
 * NOT a published index, no DB writes, no estimation of missing discounts.
 * Inputs must be adjudicated evidence from Vehicle Master; this module never
 * creates Thai identities or silently treats absence of a promotion as zero.
 */
export const PDI_METHOD = "PDI-0.5-DRAFT" as const;
export type PdiStatus = "SCORED" | "PARTIAL" | "CONFLICT" | "NOT_ELIGIBLE" | "CANDIDATE" | "SCOPE_CONFLICT";
export type PdiPowertrain = "ICE" | "HEV" | "PHEV" | "REEV" | "BEV" | string;
export type PdiEvidence = {
  sourceId: string;
  sourceRef: string;
  observedAt: string;
  effectiveFrom?: string | null;
  effectiveTo?: string | null;
  verified: boolean;
  disputed?: boolean;
};
export type PdiMsrp = PdiEvidence & { amountThb: number };
export type PdiCashBundle = PdiEvidence & {
  kind: "CASH_BUNDLE";
  amountThb: number;
  retailScope: "NATIONWIDE" | "REGION" | "DEALER" | "FLEET";
  eligibility: "GENERAL" | "FINANCE" | "TRADE_IN" | "STUDENT" | "PROFESSION" | "OTHER";
  componentIds: string[];
  stackingVerified: boolean;
};
export type PdiZeroEvidence = PdiEvidence & { kind: "ZERO_CONFIRMATION" };
export type PdiTrim = {
  trimId: string;
  powertrain: PdiPowertrain;
  currentRetail: boolean;
  msrp: PdiMsrp | null;
  competingMsrpClaims?: PdiMsrp[];
  cashEvidence: Array<PdiCashBundle | PdiZeroEvidence>;
};
export type PdiModel = {
  modelId: string;
  brandOrigin: string;
  currentRetail: boolean;
  japaneseAdmission: "APPROVED" | "CANDIDATE" | "REJECTED";
  trims: PdiTrim[];
  segment?: string | null;
  retailSetBasis?: "REVIEWED" | "MASTER_CURRENT_STATUS";
};
export type PdiInput = {
  asOf: string;
  sourceSnapshot: string;
  universeVersion: string;
  models: PdiModel[];
  publicationApproved?: boolean;
  approvedMinimumCoveragePct?: number;
};
export type PdiTrimResult = {
  trimId: string;
  msrpThb: number | null;
  discountThb: number | null;
  discountStatus: "VERIFIED_POSITIVE" | "VERIFIED_ZERO" | "UNKNOWN" | "CONFLICT";
  msrpSourceId: string | null;
  cashSourceIds: string[];
};
export type PdiModelResult = {
  modelId: string;
  status: PdiStatus;
  reason: string;
  includedTrimIds: string[];
  trims: PdiTrimResult[];
  medianMsrpThb: number | null;
  medianDiscountThb: number | null;
  pdiPct: number | null;
  medianNetOfferPriceThb: number | null;
  promoTrimBreadth: number | null;
};
export type PdiResult = {
  methodologyVersion: typeof PDI_METHOD;
  asOf: string;
  sourceSnapshot: string;
  universeVersion: string;
  modelResults: PdiModelResult[];
  eligibleModelCount: number;
  scoredModelCount: number;
  eligibleTrimCount: number;
  verifiedTrimCount: number;
  modelCoveragePct: number | null;
  trimCoveragePct: number | null;
  researchMeanPdiPct: number | null;
  publishableHeadlinePdiPct: number | null;
  publicationStatus: "NO_SCORABLE_MODELS" | "RESEARCH_ONLY" | "PUBLISHABLE";
};
function isDay(v: string): boolean { return /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v + "T00:00:00Z")); }
function applicable(e: PdiEvidence, date: string): boolean {
  return e.verified && !e.disputed && Boolean(e.sourceId) && Boolean(e.sourceRef) &&
    isDay(e.observedAt) && e.observedAt <= date &&
    (!e.effectiveFrom || e.effectiveFrom <= date) &&
    (!e.effectiveTo || e.effectiveTo >= date);
}
function median(values: number[]): number | null {
  if (!values.length) return null;
  const v = [...values].sort((a,b)=>a-b), mid=Math.floor(v.length/2);
  return v.length%2 ? v[mid] : (v[mid-1]+v[mid])/2;
}
function emptyModel(model: PdiModel, status: PdiStatus, reason: string, included: PdiTrim[] = []): PdiModelResult {
  return { modelId:model.modelId,status,reason,includedTrimIds:included.map(t=>t.trimId),
    trims:[],medianMsrpThb:null,medianDiscountThb:null,pdiPct:null,
    medianNetOfferPriceThb:null,promoTrimBreadth:null };
}
function qualifiedPowertrain(country: string, p: string): boolean {
  return country==="CN" ? ["HEV","PHEV","REEV","BEV"].includes(p)
    : country==="JP" ? ["ICE","HEV","BEV"].includes(p) : false;
}
function resolveMsrp(trim:PdiTrim,date:string): PdiMsrp | null {
  const candidates=[...(trim.msrp?[trim.msrp]:[]),...(trim.competingMsrpClaims||[])]
    .filter(p=>applicable(p,date) && Number.isSafeInteger(p.amountThb) && p.amountThb>0);
  if (!candidates.length) return null;
  if (new Set(candidates.map(p=>p.amountThb)).size!==1) return null;
  return candidates[0];
}
function conflictingMsrp(trim:PdiTrim,date:string):boolean {
  const c=[...(trim.msrp?[trim.msrp]:[]),...(trim.competingMsrpClaims||[])].filter(p=>applicable(p,date));
  return c.some(p=>p.disputed) || new Set(c.map(p=>p.amountThb)).size>1;
}
function resolveCash(trim:PdiTrim,date:string): {amount:number|null;status:PdiTrimResult["discountStatus"];refs:string[]} {
  const dispute=trim.cashEvidence.some(e=>e.disputed && e.verified && e.observedAt<=date);
  if(dispute) return {amount:null,status:"CONFLICT",refs:[]};
  const eligible=trim.cashEvidence.filter(e=>applicable(e,date));
  const bundles=eligible.filter((e):e is PdiCashBundle=>e.kind==="CASH_BUNDLE")
    .filter(e=>e.retailScope==="NATIONWIDE" && e.eligibility==="GENERAL" &&
      Number.isSafeInteger(e.amountThb) && e.amountThb>=0 &&
      e.componentIds.length>0 && (e.componentIds.length===1 || e.stackingVerified));
  const max=bundles.length ? bundles.reduce((a,b)=>a.amountThb>=b.amountThb?a:b) : null;
  if(max) return {amount:max.amountThb,status:max.amountThb>0?"VERIFIED_POSITIVE":"VERIFIED_ZERO",refs:[max.sourceId]};
  const zero=eligible.find(e=>e.kind==="ZERO_CONFIRMATION");
  if(zero) return {amount:0,status:"VERIFIED_ZERO",refs:[zero.sourceId]};
  return {amount:null,status:"UNKNOWN",refs:[]};
}
export function calculatePdi(input:PdiInput):PdiResult {
  if(!isDay(input.asOf) || !input.sourceSnapshot || !input.universeVersion) throw new Error("PDI requires valid asOf, sourceSnapshot and universeVersion");
  const seenModels=new Set<string>();
  const modelResults:PdiModelResult[]=[];
  for(const model of input.models) {
    if(seenModels.has(model.modelId)) throw new Error("duplicate modelId: "+model.modelId);
    seenModels.add(model.modelId);
    const trims=model.trims.filter(t=>t.currentRetail);
    if(!model.currentRetail || !trims.length || !["CN","JP"].includes(model.brandOrigin) || model.japaneseAdmission==="REJECTED" && model.brandOrigin==="JP") {
      modelResults.push(emptyModel(model,"NOT_ELIGIBLE","OUTSIDE_CURRENT_UNIVERSE"));continue;
    }
    const powers=trims.map(t=>qualifiedPowertrain(model.brandOrigin,t.powertrain));
    if(powers.some(Boolean) && powers.some(x=>!x)) {
      modelResults.push(emptyModel(model,"SCOPE_CONFLICT","MIXED_INCLUDED_AND_EXCLUDED_POWERTRAINS",trims));continue;
    }
    if(powers.every(x=>!x)) {modelResults.push(emptyModel(model,"NOT_ELIGIBLE","POWERTRAIN_EXCLUDED"));continue;}
    if(model.brandOrigin==="JP" && model.japaneseAdmission!=="APPROVED") {
      modelResults.push(emptyModel(model,"CANDIDATE","JAPAN_RULE_NOT_APPROVED",trims));continue;
    }
    const msrps=trims.map(t=>resolveMsrp(t,input.asOf));
    const confirmedUnderThreshold=msrps.some(p=>p!==null && p.amountThb<2_000_000);
    if(!confirmedUnderThreshold) {
      const missing=msrps.some(p=>!p);
      modelResults.push(emptyModel(model,missing?"CANDIDATE":"NOT_ELIGIBLE",missing?"PRICE_TRIGGER_UNRESOLVED":"NO_TRIM_STRICTLY_BELOW_2M",trims));continue;
    }
    const seenTrims=new Set<string>();
    const resultTrims=trims.map((t,i)=>{
      if(seenTrims.has(t.trimId)) throw new Error("duplicate trimId in model: "+t.trimId);
      seenTrims.add(t.trimId);
      const cash=resolveCash(t,input.asOf);
      return {trimId:t.trimId,msrpThb:msrps[i]?.amountThb??null,discountThb:cash.amount,
        discountStatus:cash.status,msrpSourceId:msrps[i]?.sourceId??null,cashSourceIds:cash.refs};
    });
    const conflict=trims.some(t=>conflictingMsrp(t,input.asOf)) || resultTrims.some(t=>t.discountStatus==="CONFLICT");
    const incomplete=resultTrims.some(t=>t.msrpThb===null || t.discountThb===null);
    if(conflict||incomplete) {
      const row=emptyModel(model,conflict?"CONFLICT":"PARTIAL",conflict?"EVIDENCE_CONFLICT":"MISSING_VERIFIED_TRIM_PRICE_OR_CASH",trims);
      row.trims=resultTrims;modelResults.push(row);continue;
    }
    const prices=resultTrims.map(t=>t.msrpThb as number), discounts=resultTrims.map(t=>t.discountThb as number);
    if(discounts.some((d,i)=>d>prices[i])) {
      const row=emptyModel(model,"CONFLICT","CASH_EXCEEDS_MSRP",trims);row.trims=resultTrims;modelResults.push(row);continue;
    }
    const r=median(prices) as number,c=median(discounts) as number;
    modelResults.push({
      modelId:model.modelId,status:"SCORED",reason:"ALL_RETAIL_TRIMS_VERIFIED",includedTrimIds:trims.map(t=>t.trimId),
      trims:resultTrims,medianMsrpThb:r,medianDiscountThb:c,pdiPct:100*c/r,
      medianNetOfferPriceThb:median(prices.map((p,i)=>p-discounts[i])),
      promoTrimBreadth:discounts.filter(v=>v>0).length/discounts.length
    });
  }
  const eligible=modelResults.filter(x=>["SCORED","PARTIAL","CONFLICT"].includes(x.status));
  const scored=eligible.filter(x=>x.status==="SCORED");
  const eligibleTrims=eligible.reduce((n,x)=>n+x.includedTrimIds.length,0);
  const verifiedTrims=eligible.reduce((n,x)=>n+x.trims.filter(t=>t.msrpThb!==null && t.discountThb!==null && t.discountStatus!=="CONFLICT").length,0);
  const coverage=eligible.length ? 100*scored.length/eligible.length : null;
  const mean=scored.length ? scored.reduce((n,x)=>n+(x.pdiPct as number),0)/scored.length : null;
  const publishable=mean!==null && input.publicationApproved===true &&
    typeof input.approvedMinimumCoveragePct==="number" &&
    Number.isFinite(input.approvedMinimumCoveragePct) &&
    input.approvedMinimumCoveragePct>=0 && input.approvedMinimumCoveragePct<=100 &&
    (coverage as number)>=input.approvedMinimumCoveragePct;
  return {methodologyVersion:PDI_METHOD,asOf:input.asOf,sourceSnapshot:input.sourceSnapshot,
    universeVersion:input.universeVersion,modelResults,
    eligibleModelCount:eligible.length,scoredModelCount:scored.length,
    eligibleTrimCount:eligibleTrims,verifiedTrimCount:verifiedTrims,
    modelCoveragePct:coverage,trimCoveragePct:eligibleTrims?100*verifiedTrims/eligibleTrims:null,
    researchMeanPdiPct:mean,publishableHeadlinePdiPct:publishable?mean:null,
    publicationStatus:publishable?"PUBLISHABLE":mean===null?"NO_SCORABLE_MODELS":"RESEARCH_ONLY"};
}
/** Compare common scored model IDs only. Delta is percentage POINTS, never percent. */
export function likeForLikeDeltaPp(previous:PdiResult,current:PdiResult):{commonModels:number;deltaPp:number|null} {
  const prev=new Map(previous.modelResults.filter(r=>r.status==="SCORED").map(r=>[r.modelId,r.pdiPct as number]));
  const now=current.modelResults.filter(r=>r.status==="SCORED"&&prev.has(r.modelId));
  if(!now.length)return {commonModels:0,deltaPp:null};
  return {commonModels:now.length,deltaPp:now.reduce((s,r)=>s+((r.pdiPct as number)-(prev.get(r.modelId) as number)),0)/now.length};
}
