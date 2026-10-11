/**
 * PDI v0.6 PILOT universe admission. Delegated scope selection 2026-10-11.
 * Do NOT mistake model eligibility for score completeness: the calculation
 * engine separately enforces MSRP <2m, verified full trim set, and discounts.
 *
 * National passenger-vehicle PDI only. Pickup & commercial vehicles belong to
 * a future independently calibrated subindex, not a hidden denominator.
 */
export const PDI_UNIVERSE_POLICY="PDI-UNIVERSE-2026-10-PILOT" as const;
export const PDI_PASSENGER_BODIES = [
 "SEDAN","HATCHBACK","WAGON","CROSSOVER","SUV","OFFROAD","PPV","MPV","COUPE"
] as const;
export const PDI_COMMERCIAL_BODIES = ["PICKUP","TRUCK","VAN","BUS"] as const;
/**
 * Selected Japanese retail model families. Explicit list rather than "all JP".
 * Vehicles not in this set surface CANDIDATE. All model trims remain in the
 * denominator once a listed model passes the price trigger, unless its mixed
 * powertrain classification requires a scope conflict review.
 *
 * No premium/luxury Japan brand or sport-only model enters automatically.
 * Do not infer CURRENT from this list; Vehicle Master is authoritative.
 */
export const PDI_JAPAN_MODEL_ALLOWLIST = [
 "honda.accord","honda.city","honda.city_hatchback","honda.civic","honda.crv",
 "honda.en1","honda.hrv","honda.wrv","honda.brv",
 "toyota.yaris","toyota.yaris_ativ","toyota.yaris_cross",
 "toyota.corolla_altis","toyota.corolla_cross","toyota.camry","toyota.bz4x",
 "toyota.innova_zenix","toyota.veloz",
 "nissan.almera","nissan.kicks","nissan.x_trail","nissan.serena",
 "mazda.mazda2","mazda.mazda2_hatchback","mazda.mazda3",
 "mazda.cx3","mazda.cx30","mazda.cx5",
 "mitsubishi.xforce","mitsubishi.xpander","mitsubishi.xpander_cross",
 "suzuki.swift","suzuki.fronx",
 "subaru.crosstrek","subaru.forester",
 "isuzu.mux"
] as const;
const passenger=new Set<string>(PDI_PASSENGER_BODIES);
const commercial=new Set<string>(PDI_COMMERCIAL_BODIES);
const japan=new Set<string>(PDI_JAPAN_MODEL_ALLOWLIST);
export type PdiUniverseDecision={
 policyVersion:typeof PDI_UNIVERSE_POLICY;
 bucket:"PASSENGER_HEADLINE"|"COMMERCIAL_FUTURE"|"OUTSIDE_POLICY"|"REVIEW_REQUIRED";
 japanAdmission:"APPROVED"|"CANDIDATE"|"REJECTED";
 reason:string;
};
export type UniverseModel={
 modelId:string;brandOrigin:string;bodyType:string|null;
 marketPosition?:string|null;currentRetail:boolean;
};
export function classifyPdiUniverse(m:UniverseModel):PdiUniverseDecision {
  const base={policyVersion:PDI_UNIVERSE_POLICY} as const;
  if(!m.currentRetail)return {...base,bucket:"OUTSIDE_POLICY",japanAdmission:"REJECTED",reason:"NOT_CURRENT_RETAIL"} as const;
  if(m.brandOrigin!=="CN"&&m.brandOrigin!=="JP")
    return {...base,bucket:"OUTSIDE_POLICY",japanAdmission:"REJECTED",reason:"BRAND_ORIGIN_EXCLUDED"} as const;
  if(!m.bodyType||(!passenger.has(m.bodyType)&&!commercial.has(m.bodyType)))
    return {...base,bucket:"REVIEW_REQUIRED",japanAdmission:"CANDIDATE",reason:"BODY_TYPE_UNRECOGNIZED"} as const;
  if(commercial.has(m.bodyType))
    return {...base,bucket:"COMMERCIAL_FUTURE",japanAdmission:"CANDIDATE",reason:"COMMERCIAL_REQUIRES_SEPARATE_INDEX"} as const;
  if(m.brandOrigin==="JP"&&!japan.has(m.modelId))
    return {...base,bucket:"REVIEW_REQUIRED",japanAdmission:"CANDIDATE",reason:"JAPAN_MODEL_NOT_ON_SELECTED_LIST"} as const;
  if(m.brandOrigin==="JP"&&m.marketPosition&&m.marketPosition!=="Mass")
    return {...base,bucket:"REVIEW_REQUIRED",japanAdmission:"CANDIDATE",reason:"JP_NON_MASS_POSITION"} as const;
  return {...base,bucket:"PASSENGER_HEADLINE",japanAdmission:"APPROVED",reason:m.brandOrigin==="CN"?"CN_ELIGIBLE_POWERTRAINS_ONLY":"JP_SELECTED_MODEL"} as const;
}
