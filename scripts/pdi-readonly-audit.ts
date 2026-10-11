/**
 * Internal-only, read-only PDI audit against the current TDR Vehicle Master.
 *
 * Run from repo root with a server-only Supabase secret:
 *   node --experimental-strip-types scripts/pdi-readonly-audit.ts
 *
 * No table writes, no public API, no AI inference, no auto-admission of JP cars,
 * no conversion of ambiguous campaign rows into verified cash discounts.
 */
import {adminDb} from "../lib/supabase.ts";
import {calculatePdi,type PdiModel,type PdiMsrp,type PdiTrim,type PdiCashBundle} from "../lib/pdi-engine.ts";
type Row=Record<string,any>;
const PRIMARY_KEYS:Record<string,string[]>={
  vehicle_brands:["canonical_id"],vehicle_models:["canonical_id"],
  vehicle_trims:["canonical_id"],vehicle_current_retail_sets:["model_id"],
  vehicle_price_ledger:["record_id"],vehicle_promotions:["campaign_id","option_id"],
  vehicle_campaigns:["campaign_id"]
};
async function readAll(db:any,table:string,fields:string):Promise<Row[]> {
  const keys=PRIMARY_KEYS[table];
  if(!keys)throw new Error("unknown audited table: "+table);
  const result:Row[]=[];
  for(let offset=0;offset<100_000;offset+=500) {
    // Stable full-PK ordering is mandatory across range pages; otherwise
    // PostgREST may skip/duplicate tied rows as the page boundary shifts.
    let query=db.from(table).select(fields);
    for(const key of keys)query=query.order(key,{ascending:true});
    const {data,error}=await query.range(offset,offset+499);
    if(error)throw new Error(table+" read failure: "+error.message);
    const page=(data||[]) as Row[];
    result.push(...page);
    if(page.length<500)return result;
  }
  throw new Error(table+" unexpectedly exceeds bounded audit pagination");
}
function dateDay(value:unknown):string|null {
  return typeof value==="string" && /^\d{4}-\d{2}-\d{2}$/.test(value)?value:null;
}
function isActiveOn(row:Row,asOf:string):boolean {
  return (!row.effective_from || row.effective_from<=asOf) &&
    (!row.effective_to || row.effective_to>=asOf) &&
    (!row.observed_at || row.observed_at<=asOf);
}
async function main() {
  const db=adminDb();
  if(!db)throw new Error("SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY required (server only)");
  const {data:state,error:stateError}=await db.from("vehicle_master_state")
    .select("seed_as_of,seed_release_id,seed_source_hash").eq("scope","vehicle_master").single();
  if(stateError||!state)throw new Error("Vehicle Master seed state missing");
  const asOf=state.seed_as_of as string;
  const [brands,models,trims,retailSets,prices,promotions,campaigns]=await Promise.all([
    readAll(db,"vehicle_brands","canonical_id,origin_country,deleted_at"),
    readAll(db,"vehicle_models","canonical_id,brand_id,status,deleted_at"),
    readAll(db,"vehicle_trims","canonical_id,model_id,status,powertrain,deleted_at"),
    readAll(db,"vehicle_current_retail_sets","model_id,trim_ids"),
    readAll(db,"vehicle_price_ledger","record_id,trim_id,amount_thb,price_type,effective_from,effective_to,observed_at,source,source_ref,authority,in_release,retracted_at"),
    readAll(db,"vehicle_promotions","campaign_id,option_id,trim_id,model_id,scope,type,amount_thb,valid_from,valid_to,valid_to_assumed,last_seen_at,source,authority,status,option_status,conditions"),
    readAll(db,"vehicle_campaigns","campaign_id,source_ref,starts,ends")
  ]);
  const origin=new Map(brands.filter(b=>!b.deleted_at).map(b=>[b.canonical_id,b.origin_country]));
  const set=new Map(retailSets.map(r=>[r.model_id,new Set<string>(r.trim_ids||[])]));
  const pricesByTrim=new Map<string,Row[]>();
  let observedListPriceCount=0,adjudicatedMsrpCount=0;
  for(const r of prices) {
    if(r.price_type!=="LIST_PRICE" || !r.in_release || r.retracted_at || !isActiveOn(r,asOf)) continue;
    observedListPriceCount++;
    const arr=pricesByTrim.get(r.trim_id)||[];arr.push(r);pricesByTrim.set(r.trim_id,arr);
  }
  const campaignById=new Map(campaigns.map(c=>[c.campaign_id,c]));
  const promosByTrim=new Map<string,PdiCashBundle[]>();
  let qualifiedCashBundleCount=0;
  for(const p of promotions) {
    const conditions=p.conditions||{};
    // These positive flags must be explicit and owner-reviewed. Legacy records
    // with NULL type/scope/status must NEVER be guessed or treated as cash.
    if(p.type!=="DISCOUNT"||p.scope!=="TRIM"||!p.trim_id||
      p.status!=="ACTIVE"||p.option_status!=="ACTIVE"||
      !["ADMIN","OFFICIAL"].includes(p.authority)||p.valid_to_assumed||
      !p.valid_from||!p.valid_to||p.valid_from>asOf||p.valid_to<asOf||
      conditions.pdi_verified_general_cash!==true||
      conditions.retail_scope!=="NATIONWIDE"||
      !Number.isSafeInteger(Number(p.amount_thb))||Number(p.amount_thb)<0)continue;
    const campaign=campaignById.get(p.campaign_id);
    const ref=campaign?.source_ref||null;
    if(!ref)continue;
    const observedAt=dateDay(p.last_seen_at)||dateDay(p.valid_from);
    if(!observedAt || observedAt>asOf)continue;
    const entry:PdiCashBundle={
      kind:"CASH_BUNDLE",amountThb:Number(p.amount_thb),
      retailScope:"NATIONWIDE",eligibility:"GENERAL",
      componentIds:[p.campaign_id+":"+p.option_id],stackingVerified:false,
      sourceId:p.campaign_id+":"+p.option_id,sourceRef:ref,
      observedAt,effectiveFrom:p.valid_from,effectiveTo:p.valid_to,verified:true
    };
    const rows=promosByTrim.get(p.trim_id)||[];rows.push(entry);promosByTrim.set(p.trim_id,rows);
    qualifiedCashBundleCount++;
  }
  const byModel=new Map<string,Row[]>();
  for(const t of trims) {
    if(t.deleted_at)continue;
    const arr=byModel.get(t.model_id)||[];arr.push(t);byModel.set(t.model_id,arr);
  }
  const pdiModels:PdiModel[]=[];
  for(const m of models) {
    if(m.deleted_at || m.status!=="CURRENT")continue;
    const selected:Set<string>|undefined=set.get(m.canonical_id);
    const current=(byModel.get(m.canonical_id)||[]).filter(t=>selected?selected.has(t.canonical_id):t.status==="CURRENT");
    if(!current.length)continue;
    const calcTrims:PdiTrim[]=current.map(t=>{
      const options=(pricesByTrim.get(t.canonical_id)||[]).sort((a,b)=>
        String(b.observed_at||"").localeCompare(String(a.observed_at||""))||
        String(b.effective_from||"").localeCompare(String(a.effective_from||"")));
      const best=options[0];
      const optionsAtSameTime=best?options.filter(p=>p.observed_at===best.observed_at&&p.effective_from===best.effective_from):[];
      // authority NULL in legacy seed is NOT proof of official verification.
      function msrp(row:Row):PdiMsrp {
        const verified=["ADMIN","OFFICIAL"].includes(row.authority)&&
          Boolean(row.source_ref)&&Number.isSafeInteger(Number(row.amount_thb));
        if(verified)adjudicatedMsrpCount++;
        return {amountThb:Number(row.amount_thb),sourceId:row.record_id,
          sourceRef:row.source_ref||"",observedAt:dateDay(row.observed_at)||"",
          effectiveFrom:row.effective_from,effectiveTo:row.effective_to,verified};
      }
      return {
        trimId:t.canonical_id,powertrain:t.powertrain,currentRetail:true,
        msrp:best?msrp(best):null,
        competingMsrpClaims:optionsAtSameTime.slice(1).map(msrp),
        cashEvidence:promosByTrim.get(t.canonical_id)||[]
      };
    });
    pdiModels.push({modelId:m.canonical_id,brandOrigin:origin.get(m.brand_id)||"",
      currentRetail:true,japaneseAdmission:"CANDIDATE",trims:calcTrims,
      retailSetBasis:selected?"REVIEWED":"MASTER_CURRENT_STATUS"});
  }
  const output=calculatePdi({asOf,sourceSnapshot:state.seed_release_id+":"+state.seed_source_hash,
    universeVersion:asOf.slice(0,7)+":draft-discovery",models:pdiModels});
  const statusCounts:Record<string,number>={};
  for(const item of output.modelResults)statusCounts[item.status]=(statusCounts[item.status]||0)+1;
  const report={
    evidenceGate:"INTERNAL_AUDIT_ONLY; v0.5 draft not approved for publishing",
    source:"TDR Vehicle Master read-only, no external guessed observations",
    asOf,
    vehicleMasterRelease:state.seed_release_id,
    audit:{currentModels:models.filter(m=>m.status==="CURRENT"&&!m.deleted_at).length,
      examinedModels:pdiModels.length,
      observedListPriceCount,
      adjudicatedMsrpCount,
      legacyPromotionsWithoutTypedClassification:promotions.filter(p=>!p.type||!p.scope||!p.status).length,
      promotionsTotal:promotions.length,
      qualifiedCashBundleCount,
      japaneseAdmission:"CANDIDATE_PENDING_OWNER_APPROVED_RULE",
      statusCounts},
    index:{methodologyVersion:output.methodologyVersion,
      eligibleModelCount:output.eligibleModelCount,scoredModelCount:output.scoredModelCount,
      eligibleTrimCount:output.eligibleTrimCount,verifiedTrimCount:output.verifiedTrimCount,
      modelCoveragePct:output.modelCoveragePct,trimCoveragePct:output.trimCoveragePct,
      researchMeanPdiPct:output.researchMeanPdiPct,
      publishableHeadlinePdiPct:output.publishableHeadlinePdiPct,
      publicationStatus:output.publicationStatus},
    reviewQueue:output.modelResults.filter(r=>r.status!=="SCORED")
      .map(r=>({modelId:r.modelId,status:r.status,reason:r.reason,trimCount:r.includedTrimIds.length}))
  };
  process.stdout.write(JSON.stringify(report,null,2)+"\n");
}
main().catch(e=>{console.error("PDI audit failed:",e instanceof Error?e.message:e);process.exitCode=1;});
