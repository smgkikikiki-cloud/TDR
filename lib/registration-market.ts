export type MarketDimension =
  | "brand"
  | "model"
  | "segment"
  | "body_type"
  | "powertrain"
  | "oem_group"
  | "market_position"
  | "import_type"
  | "origin_country"
  | "brand_origin"
  | "registration_type"
  | "market_scope";

export type MarketWindow = "month" | "rolling3" | "rolling6" | "rolling12" | "ytd";
export type MarketComparison = "previous" | "yoy";

export type MarketPeriodWindow = { from: string; to: string };
export type MarketSliceFilters = {
  registrationTypes?: string[]; brandIds?: string[]; modelIds?: string[]; segments?: string[];
  bodyTypes?: string[]; powertrains?: string[]; oemGroups?: string[]; marketPositions?: string[];
  importTypes?: string[]; originCountries?: string[]; brandOrigins?: string[]; marketScopes?: string[];
};
export type CanonicalRegistrationFact = {
  period: string; registration_type: string; registrations: number;
  canonical_model_id: string | null; canonical_brand_id: string | null;
  brand_name: string; model_name: string; segment: string; body_type: string; powertrain: string;
  oem_group: string; market_position: string; import_type: string; origin_country: string;
  brand_origin: string; market_scope: string; raw_brand_name: string; raw_model_name: string;
  brand_mapped: boolean; canonically_mapped: boolean;
};
export type MarketSliceRow = {
  entity_key: string; entity_label: string; registrations: number | string; market_total: number | string;
  market_share_pct: number | string; market_rank: number | string; window_raw_units: number | string;
  window_mapped_units: number | string; window_mapping_coverage_pct: number | string;
};
export type MarketMovementRow = {
  entity_key: string; entity_label: string; units_previous: number; units_current: number; units_change: number;
  share_previous_pct: number; share_current_pct: number; share_change_pp: number;
  rank_previous: number | null; rank_current: number | null; rank_change: number | null;
};

const MARKET_DIMENSIONS = new Set<MarketDimension>(["brand","model","segment","body_type","powertrain","oem_group","market_position","import_type","origin_country","brand_origin","registration_type","market_scope"]);
const MARKET_WINDOWS = new Set<MarketWindow>(["month","rolling3","rolling6","rolling12","ytd"]);
const MARKET_COMPARISONS = new Set<MarketComparison>(["previous","yoy"]);
const BRAND_GRAIN_DIMENSIONS = new Set<MarketDimension>(["brand","oem_group","brand_origin"]);
export function isMarketDimension(value: string | null): value is MarketDimension { return Boolean(value && MARKET_DIMENSIONS.has(value as MarketDimension)); }
export function isMarketWindow(value: string | null): value is MarketWindow { return Boolean(value && MARKET_WINDOWS.has(value as MarketWindow)); }
export function isMarketComparison(value: string | null): value is MarketComparison { return Boolean(value && MARKET_COMPARISONS.has(value as MarketComparison)); }
export function normalizeReportPeriod(value: string | null): string | null {
  if (!value) return null; const match = /^(\d{4})-(\d{2})(?:-\d{2})?$/.exec(value); if (!match) return null;
  const month = Number(match[2]); if (month < 1 || month > 12) return null; return `${match[1]}-${match[2]}-01`;
}
function periodIndex(value: string): number { const normalized = normalizeReportPeriod(value); if (!normalized) throw new Error(`invalid report period: ${value}`); return Number(normalized.slice(0,4))*12 + Number(normalized.slice(5,7)) - 1; }
function periodFromIndex(value: number): string { const year = Math.floor(value/12); const month = value%12+1; return `${String(year).padStart(4,"0")}-${String(month).padStart(2,"0")}-01`; }
export function shiftReportPeriod(value: string, months: number): string { return periodFromIndex(periodIndex(value)+Math.trunc(months)); }
export function resolveMarketWindow(period: string, window: MarketWindow): MarketPeriodWindow {
  const normalized = normalizeReportPeriod(period); if (!normalized) throw new Error(`invalid report period: ${period}`);
  if (window === "month") return { from: normalized, to: normalized }; if (window === "ytd") return { from: `${normalized.slice(0,4)}-01-01`, to: normalized };
  const months = window === "rolling3" ? 3 : window === "rolling6" ? 6 : 12; return { from: shiftReportPeriod(normalized, -(months-1)), to: normalized };
}
export function previousMarketWindow(window: MarketPeriodWindow): MarketPeriodWindow { const width = periodIndex(window.to)-periodIndex(window.from)+1; if (width<1) throw new Error("market window end precedes start"); const previousTo=shiftReportPeriod(window.from,-1); return { from: shiftReportPeriod(previousTo,-(width-1)), to: previousTo }; }
export function comparisonMarketWindow(window: MarketPeriodWindow, comparison: MarketComparison): MarketPeriodWindow { return comparison === "previous" ? previousMarketWindow(window) : { from: shiftReportPeriod(window.from,-12), to: shiftReportPeriod(window.to,-12) }; }
export function reportPeriods(window: MarketPeriodWindow): string[] { const first=periodIndex(window.from), last=periodIndex(window.to); if(last<first) throw new Error("market window end precedes start"); return Array.from({length:last-first+1},(_,i)=>periodFromIndex(first+i)); }
export function missingReportPeriods(window: MarketPeriodWindow, available: Iterable<string>): string[] { const known=new Set(Array.from(available,(p)=>normalizeReportPeriod(p)).filter(Boolean)); return reportPeriods(window).filter((p)=>!known.has(p)); }
function allowed(values: string[] | undefined, value: string | null): boolean { return !values?.length || Boolean(value && values.includes(value)); }
function displayValue(value: string | null | undefined): string { return value && value.trim() ? value : "UNKNOWN"; }
function rawKey(value: string): string { return encodeURIComponent(value.trim().toLocaleLowerCase().replace(/\s+/g," ")); }
function entity(fact: CanonicalRegistrationFact, dimension: MarketDimension): [string,string] {
  switch(dimension){
    case "brand": return [fact.canonical_brand_id || `raw-brand:${rawKey(fact.raw_brand_name)}`, fact.brand_name];
    case "model": return [fact.canonical_model_id || `raw-model:${rawKey(fact.raw_brand_name)}:${rawKey(fact.raw_model_name)}`, [fact.brand_name,fact.model_name].filter(Boolean).join(" ")];
    case "segment": return [fact.segment,fact.segment]; case "body_type": return [fact.body_type,fact.body_type]; case "powertrain": return [fact.powertrain,fact.powertrain];
    case "oem_group": return [fact.oem_group,fact.oem_group]; case "market_position": return [fact.market_position,fact.market_position]; case "import_type": return [fact.import_type,fact.import_type];
    case "origin_country": return [fact.origin_country,fact.origin_country]; case "brand_origin": return [fact.brand_origin,fact.brand_origin]; case "registration_type": return [fact.registration_type,fact.registration_type]; case "market_scope": return [fact.market_scope,fact.market_scope];
  }
}
function passesFilters(fact: CanonicalRegistrationFact, dimension: MarketDimension, filters: MarketSliceFilters, openDimensionFilter = true): boolean {
  return ((!openDimensionFilter || dimension !== "registration_type") ? allowed(filters.registrationTypes,fact.registration_type) : true)
    && ((!openDimensionFilter || dimension !== "brand") ? allowed(filters.brandIds,fact.canonical_brand_id) : true)
    && ((!openDimensionFilter || dimension !== "model") ? allowed(filters.modelIds,fact.canonical_model_id) : true)
    && ((!openDimensionFilter || dimension !== "segment") ? allowed(filters.segments,fact.segment) : true)
    && ((!openDimensionFilter || dimension !== "body_type") ? allowed(filters.bodyTypes,fact.body_type) : true)
    && ((!openDimensionFilter || dimension !== "powertrain") ? allowed(filters.powertrains,fact.powertrain) : true)
    && ((!openDimensionFilter || dimension !== "oem_group") ? allowed(filters.oemGroups,fact.oem_group) : true)
    && ((!openDimensionFilter || dimension !== "market_position") ? allowed(filters.marketPositions,fact.market_position) : true)
    && ((!openDimensionFilter || dimension !== "import_type") ? allowed(filters.importTypes,fact.import_type) : true)
    && ((!openDimensionFilter || dimension !== "origin_country") ? allowed(filters.originCountries,fact.origin_country) : true)
    && ((!openDimensionFilter || dimension !== "brand_origin") ? allowed(filters.brandOrigins,fact.brand_origin) : true)
    && ((!openDimensionFilter || dimension !== "market_scope") ? allowed(filters.marketScopes,fact.market_scope) : true);
}
export function sliceMarketFacts(args: { facts: CanonicalRegistrationFact[]; dimension: MarketDimension; filters?: MarketSliceFilters; includeUnmapped?: boolean; limit?: number; openDimensionFilter?: boolean }): MarketSliceRow[] {
  const filters=args.filters||{}; const limit=Math.min(Math.max(Math.trunc(args.limit??100),1),500); const openDimensionFilter=args.openDimensionFilter !== false;
  const coverageFacts=args.facts.filter((fact)=> openDimensionFilter && args.dimension === "registration_type" ? true : allowed(filters.registrationTypes,fact.registration_type));
  const windowRawUnits=coverageFacts.reduce((sum,fact)=>sum+Number(fact.registrations||0),0);
  const windowMappedUnits=coverageFacts.filter((fact)=>fact.canonically_mapped).reduce((sum,fact)=>sum+Number(fact.registrations||0),0);
  const grouped=new Map<string,{label:string;units:number}>();
  for(const fact of coverageFacts){ const usable=args.includeUnmapped || fact.canonically_mapped || (BRAND_GRAIN_DIMENSIONS.has(args.dimension)&&fact.brand_mapped); if(!usable || !passesFilters(fact,args.dimension,filters,openDimensionFilter)) continue; const [key,label]=entity(fact,args.dimension); if(!key) continue; const previous=grouped.get(key); grouped.set(key,{label:displayValue(label),units:(previous?.units||0)+Number(fact.registrations||0)}); }
  const ranked=[...grouped.entries()].map(([key,row])=>({key,...row})).sort((a,b)=>b.units-a.units||a.key.localeCompare(b.key)); const marketTotal=ranked.reduce((sum,row)=>sum+row.units,0); const mappingCoverage=windowRawUnits?Math.round((1000*windowMappedUnits)/windowRawUnits)/10:0;
  return ranked.slice(0,limit).map((row,index)=>({entity_key:row.key,entity_label:row.label,registrations:row.units,market_total:marketTotal,market_share_pct:marketTotal?Math.round((10000*row.units)/marketTotal)/100:0,market_rank:index+1,window_raw_units:windowRawUnits,window_mapped_units:windowMappedUnits,window_mapping_coverage_pct:mappingCoverage}));
}
export function compareMarketSliceRows(previousRows: MarketSliceRow[], currentRows: MarketSliceRow[]): MarketMovementRow[] {
  const previous=new Map(previousRows.map((row)=>[row.entity_key,row])); const current=new Map(currentRows.map((row)=>[row.entity_key,row])); const keys=new Set([...previous.keys(),...current.keys()]); const rows:MarketMovementRow[]=[];
  for(const key of keys){ const left=previous.get(key),right=current.get(key); const unitsPrevious=Number(left?.registrations||0),unitsCurrent=Number(right?.registrations||0),sharePrevious=Number(left?.market_share_pct||0),shareCurrent=Number(right?.market_share_pct||0); const rankPrevious=left?.market_rank==null?null:Number(left.market_rank), rankCurrent=right?.market_rank==null?null:Number(right.market_rank); rows.push({entity_key:key,entity_label:right?.entity_label||left?.entity_label||key,units_previous:unitsPrevious,units_current:unitsCurrent,units_change:unitsCurrent-unitsPrevious,share_previous_pct:sharePrevious,share_current_pct:shareCurrent,share_change_pp:shareCurrent-sharePrevious,rank_previous:rankPrevious,rank_current:rankCurrent,rank_change:rankPrevious!=null&&rankCurrent!=null?rankPrevious-rankCurrent:null}); }
  return rows.sort((a,b)=>b.share_change_pp-a.share_change_pp||b.units_current-a.units_current||a.entity_key.localeCompare(b.entity_key));
}
