import fs from "node:fs";
import {
  assemblePublicMarket,
  resolveIcePowertrainRow,
  resolveModelGroupRedirect,
  resolveWheelTyreAvailability,
  sliceIceByBodyType,
  sliceIceByBrand,
  sliceIceByModel,
  sliceIceByPowertrain,
  sliceIceByRegistrationType,
  sliceIceByRimBucket,
  sliceIceBySegment,
  sliceIceByTyreSize,
  wheelTyreCoverage,
  iceUnitChangePct,
  UNMAPPED_LABEL,
  type IceCrosswalkLink,
  type IceRegPowertrainRow,
  type IceRegProvinceRow,
  type IceRegTrendRow,
  type IceRimProvinceRow,
  type IceTyreCoverageRow,
  type IceTyreProvinceRow,
  type VehicleModelDim,
} from "../lib/ice-market-engine.ts";
import type { MarketSliceRow } from "../lib/registration-market.ts";
import type { PublicMarket } from "../lib/public-market.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

// ---------------------------------------------------------------------------
// §11 synthetic fixture -- one coherent market, reconcilable across panels.
// Buddhist period strings, as Ice delivers them (never a SQL date).
// ---------------------------------------------------------------------------

const P1 = "2569-06";
const P2 = "2569-07";
const P3 = "2569-08";
const BKK = "กรุงเทพมหานคร";
const CHON = "ชลบุรี";

const regProvinceP3: IceRegProvinceRow[] = [
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", fuel_group: "ICE", reg_count: 130 },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", fuel_group: "BEV", reg_count: 20 },
  { period: P3, province: CHON, reg_type: "RY1", brand: "Toyota", fuel_group: "ICE", reg_count: 20 },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Honda", fuel_group: "ICE", reg_count: 70 },
  { period: P3, province: CHON, reg_type: "RY2", brand: "Honda", fuel_group: "ICE", reg_count: 40 },
];
const regProvinceP2: IceRegProvinceRow[] = [
  { period: P2, province: BKK, reg_type: "RY1", brand: "Toyota", fuel_group: "ICE", reg_count: 90 },
  { period: P2, province: BKK, reg_type: "RY1", brand: "Honda", fuel_group: "ICE", reg_count: 70 },
];

const regTrendP3: IceRegTrendRow[] = [
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", model_group_id: "toyota.model-x", model_name: "Model X", reg_count: 60 },
  { period: P3, province: CHON, reg_type: "RY1", brand: "Toyota", model_group_id: "toyota.model-x", model_name: "Model X", reg_count: 20 },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", model_group_id: "toyota.model-y", model_name: "Model Y", reg_count: 90 },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Honda", model_group_id: "honda.model-z", model_name: "Model Z", reg_count: 70 },
  { period: P3, province: CHON, reg_type: "RY2", brand: "Honda", model_group_id: "honda.model-z", model_name: "Model Z", reg_count: 40 },
];

const crosswalk: IceCrosswalkLink[] = [
  { model_group_id: "toyota.model-x", canonical_model_id: "toyota.canon_x", status: "AUTO" },
  { model_group_id: "honda.model-z", canonical_model_id: "honda.canon_z1", status: "AUTO" },
  { model_group_id: "honda.model-z", canonical_model_id: "honda.canon_z2", status: "APPROVED" },
  // toyota.model-y has no crosswalk row at all -- genuinely unmatched.
  // A PROPOSED/REJECTED row must never surface as an active link.
  { model_group_id: "toyota.model-y", canonical_model_id: "toyota.canon_y_candidate", status: "PROPOSED" },
];

const vehicleModels: VehicleModelDim[] = [
  { canonical_id: "toyota.canon_x", segment: "C", body_type: "SEDAN" },
  { canonical_id: "honda.canon_z1", segment: "D", body_type: "CROSSOVER" },
  { canonical_id: "honda.canon_z2", segment: "D", body_type: "CROSSOVER" },
];

const regPowertrainP3: IceRegPowertrainRow[] = [
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", model_group_id: "toyota.model-x", model_name: "Model X",
    fuel_group: "BEV", reg_est: 15, reg_min: null, reg_max: null, certainty: "exact" },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", model_group_id: "toyota.model-x", model_name: "Model X",
    fuel_group: "ICE", reg_est: 45, reg_min: null, reg_max: null, certainty: "family" },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Honda", model_group_id: "honda.model-z", model_name: "Model Z",
    fuel_group: "ICE", reg_est: null, reg_min: 60, reg_max: 80, certainty: "range" },
];

const rimProvinceP3: IceRimProvinceRow[] = [
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", rim_bucket: "15-16", reg_est: 50 },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", rim_bucket: "17+", reg_est: 30 },
];
const tyreProvinceP3: IceTyreProvinceRow[] = [
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", tyre_size: "205/55R16", rim_inch: 16, reg_est: 40 },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", tyre_size: "215/60R17", rim_inch: 17, reg_est: 25 },
];
const tyreCoverageP3: IceTyreCoverageRow[] = [
  { period: P3, province: BKK, reg_type: "RY1", brand: "Toyota", reg_total: 150, reg_tyre_known: 100 },
  { period: P3, province: BKK, reg_type: "RY1", brand: "Honda", reg_total: 50, reg_tyre_known: 50 },
];

// ===========================================================================

console.log("brand / registration_type dimensions (ice_reg_province -- exact units)");
const brandAll = sliceIceByBrand(regProvinceP3);
check("period total equals the synthetic Ice total exactly",
  brandAll.reduce((s, r) => s + Number(r.registrations), 0), 280);
check("brand ranking", brandAll.map((r) => [r.entity_key, r.registrations]), [["Toyota", 170], ["Honda", 110]]);
check("brand coverage is always 100% -- Ice is authoritative, nothing is ever unmapped",
  brandAll[0].window_mapping_coverage_pct, 100);
check("brand market share", brandAll.map((r) => r.market_share_pct), [60.71, 39.29]);

const brandByProvince = sliceIceByBrand(regProvinceP3, { provinces: [BKK] });
check("filtering by province preserves exact totals",
  brandByProvince.reduce((s, r) => s + Number(r.registrations), 0), 220);
check("province filter narrows per brand", brandByProvince.map((r) => [r.entity_key, r.registrations]),
  [["Toyota", 150], ["Honda", 70]]);

const brandByRegType = sliceIceByBrand(regProvinceP3, { registrationTypes: ["RY1"] });
check("filtering by registration_type preserves exact totals",
  brandByRegType.reduce((s, r) => s + Number(r.registrations), 0), 240);

const regTypeSlice = sliceIceByRegistrationType(regProvinceP3);
check("registration_type slice totals reconcile with reg_trend's own split",
  regTypeSlice.map((r) => [r.entity_key, r.registrations]), [["RY1", 240], ["RY2", 40]]);

console.log("\nmodel dimension (ice_reg_trend) -- Ice model_group_id is the market identity");
const modelAll = sliceIceByModel(regTrendP3, crosswalk);
check("no units disappear merely because an Ice model is unmatched",
  modelAll.reduce((s, r) => s + Number(r.registrations), 0), 280);
check("ranking and units", modelAll.map((r) => [r.entity_key, r.registrations]),
  [["honda.model-z", 110], ["toyota.model-y", 90], ["toyota.model-x", 80]]);
check("matched Ice group links to its canonical_model_id",
  modelAll.find((r) => r.entity_key === "toyota.model-x")?.canonical_model_id, "toyota.canon_x");
check("unmatched Ice group remains visible and unlinked",
  modelAll.find((r) => r.entity_key === "toyota.model-y")?.canonical_model_id, null);
check("a PROPOSED crosswalk row is never surfaced as an active link",
  modelAll.find((r) => r.entity_key === "toyota.model-y")?.canonical_model_id, null);
check("many TDR models -> one Ice group resolves to one deterministic link",
  modelAll.find((r) => r.entity_key === "honda.model-z")?.canonical_model_id, "honda.canon_z1");
check("model dimension coverage is also always 100%",
  modelAll[0].window_mapping_coverage_pct, 100);

console.log("\nsegment / body_type (TDR Vehicle DB via APPROVED/AUTO crosswalk)");
const segmentAll = sliceIceBySegment(regTrendP3, crosswalk, vehicleModels);
check("matched + ไม่ระบุ = total Ice units",
  segmentAll.reduce((s, r) => s + Number(r.registrations), 0), 280);
check("matched units aggregate from the TDR dimension",
  segmentAll.find((r) => r.entity_key === "C")?.registrations, 80);
check("many-TDR-models-agree group aggregates correctly",
  segmentAll.find((r) => r.entity_key === "D")?.registrations, 110);
check("unmatched units go to ไม่ระบุ",
  segmentAll.find((r) => r.entity_key === UNMAPPED_LABEL)?.registrations, 90);
check("coverage percentage is correct", segmentAll[0].window_mapping_coverage_pct, 67.9);

const bodyAll = sliceIceByBodyType(regTrendP3, crosswalk, vehicleModels);
check("body_type follows the same rule as segment",
  bodyAll.map((r) => [r.entity_key, r.registrations]).sort(),
  [["CROSSOVER", 110], ["SEDAN", 80], [UNMAPPED_LABEL, 90]].sort());

console.log("\nsibling disagreement -- many TDR models mapped to one group that disagree");
const disagreeingCrosswalk: IceCrosswalkLink[] = [
  { model_group_id: "x.group", canonical_model_id: "x.a", status: "AUTO" },
  { model_group_id: "x.group", canonical_model_id: "x.b", status: "APPROVED" },
];
const disagreeingModels: VehicleModelDim[] = [
  { canonical_id: "x.a", segment: "B", body_type: "HATCHBACK" },
  { canonical_id: "x.b", segment: "C", body_type: "HATCHBACK" },
];
const disagreeingTrend: IceRegTrendRow[] = [
  { period: P3, province: BKK, reg_type: "RY1", brand: "X", model_group_id: "x.group", model_name: "Group", reg_count: 50 },
];
const disagreeingSegment = sliceIceBySegment(disagreeingTrend, disagreeingCrosswalk, disagreeingModels);
check("disagreeing siblings fall back to ไม่ระบุ for segment, never an arbitrary pick",
  disagreeingSegment.map((r) => [r.entity_key, r.registrations]), [[UNMAPPED_LABEL, 50]]);
const disagreeingBody = sliceIceByBodyType(disagreeingTrend, disagreeingCrosswalk, disagreeingModels);
check("siblings that DO agree on body_type still aggregate normally",
  disagreeingBody.map((r) => [r.entity_key, r.registrations]), [["HATCHBACK", 50]]);

console.log("\npowertrain (ice_reg_powertrain + fuel_group ONLY -- never Vehicle DB regrouping)");
const resolvedExact = resolveIcePowertrainRow(regPowertrainP3[0]);
check("exact certainty uses reg_est", resolvedExact, { value: 15, certainty: "exact", reg_min: null, reg_max: null, note: null });
const resolvedFamily = resolveIcePowertrainRow(regPowertrainP3[1]);
check("family certainty uses reg_est and carries the required note",
  resolvedFamily, { value: 45, certainty: "family", reg_min: null, reg_max: null, note: "แบ่งระหว่างรุ่นในตระกูลโดย TDR" });
check("the note is never the word ประมาณการ", resolvedFamily.note?.includes("ประมาณการ"), false);
const resolvedRange = resolveIcePowertrainRow(regPowertrainP3[2]);
check("range certainty exposes reg_min/reg_max", resolvedRange, { value: 70, certainty: "range", reg_min: 60, reg_max: 80, note: null });

const powertrainSlice = sliceIceByPowertrain(regPowertrainP3);
check("powertrain totals equal the synthetic ice_reg_powertrain rows exactly",
  powertrainSlice.reduce((s, r) => s + Number(r.registrations), 0), 130);
check("powertrain grouping is by fuel_group, not a Vehicle DB taxonomy",
  powertrainSlice.map((r) => [r.entity_key, r.registrations]).sort(), [["BEV", 15], ["ICE", 115]].sort());

console.log("\nwheel / tyre (\"TDR Wheel & Tyre Index\")");
const rimSlice = sliceIceByRimBucket(rimProvinceP3);
check("rim values are taken from the Ice fixture exactly",
  rimSlice.map((r) => [r.entity_key, r.registrations]), [["15-16", 50], ["17+", 30]]);
const tyreSlice = sliceIceByTyreSize(tyreProvinceP3);
check("tyre values are taken from the Ice fixture exactly",
  tyreSlice.map((r) => [r.entity_key, r.registrations]), [["205/55R16", 40], ["215/60R17", 25]]);
const coverage = wheelTyreCoverage(tyreCoverageP3);
check("coverage is exposed and correct", coverage, { regTotal: 200, regKnown: 150, coveragePct: 75 });

check("published start controls availability -- before period_from",
  resolveWheelTyreAvailability("2567-01", "2566-12").available, false);
check("published start controls availability -- at/after period_from",
  resolveWheelTyreAvailability("2567-01", "2567-01").available, true);
check("no start period is hard-coded in the engine module",
  !fs.readFileSync("lib/ice-market-engine.ts", "utf8").includes("2564-01"));

console.log("\npercent-change display rule (base < 30 units -> no percentage)");
check("comparison base below 30 -> no percentage-change output", iceUnitChangePct(25, 40), null);
check("comparison base at 30 -> percentage change allowed", iceUnitChangePct(30, 33), 10);
check("comparison base above 30 -> percentage change allowed", iceUnitChangePct(100, 115), 15);
check("a negative base is still gated the same way", iceUnitChangePct(0, 10), null);

console.log("\nredirect resolver (ice_model_group_redirects) -- cycle-safe, chain-aware");
check("an id with no redirect resolves to itself",
  resolveModelGroupRedirect("solo-group", []), { resolved: "solo-group", hops: 0, cycle: false });
check("a single redirect hop resolves to the new id",
  resolveModelGroupRedirect("old-id", [{ old_model_group_id: "old-id", new_model_group_id: "new-id" }]),
  { resolved: "new-id", hops: 1, cycle: false });
check("a chained redirect follows every hop",
  resolveModelGroupRedirect("a", [
    { old_model_group_id: "a", new_model_group_id: "b" },
    { old_model_group_id: "b", new_model_group_id: "c" },
  ]),
  { resolved: "c", hops: 2, cycle: false });
check("a cycle is detected rather than looping forever",
  resolveModelGroupRedirect("p", [
    { old_model_group_id: "p", new_model_group_id: "q" },
    { old_model_group_id: "q", new_model_group_id: "p" },
  ]).cycle, true);

console.log("\nmovement / comparison (reusing compareMarketSliceRows, no legacy semantics)");
const previousBrand = sliceIceByBrand(regProvinceP2);
check("previous-period Ice total", previousBrand.reduce((s, r) => s + Number(r.registrations), 0), 160);

// ---------------------------------------------------------------------------
// §6 -- PublicMarket shape / top-8+others / movers / trend
// ---------------------------------------------------------------------------

console.log("\npublic market adapter -- shape and algorithm unchanged from lib/public-market.ts");
function row(key: string, units: number, total: number): MarketSliceRow {
  return {
    entity_key: key, entity_label: key, registrations: units, market_total: total,
    market_share_pct: total ? Math.round((10000 * units) / total) / 100 : 0, market_rank: 1,
    window_raw_units: total, window_mapped_units: total, window_mapping_coverage_pct: 100,
  };
}
const nineBrandRows: MarketSliceRow[] = Array.from({ length: 9 }, (_, i) => row(`brand-${i}`, 90 - i * 10, 450));
const assembled = assemblePublicMarket({
  dimension: "brand" as PublicMarket["dimension"],
  period: P3,
  previousPeriod: P2,
  currentRows: nineBrandRows,
  currentTotal: 450,
  previousRows: [row("brand-0", 50, 450)],
  brandLimit: 8,
  trend: [{ period: P1, total: null }, { period: P2, total: 160 }, { period: P3, total: 450 }],
});
check("PublicMarket shape keys unchanged",
  Object.keys(assembled).sort(),
  ["brands", "dimension", "movers", "others", "period", "previousPeriod", "totalRegistrations", "trend"].sort());
check("top-8 + others behavior unchanged", assembled.brands.length, 8);
check("the 9th row folds into others", assembled.others?.registrations, 10);
check("absent period remains null/no-data per contract", assembled.trend[0].total, null);
check("12-month trend semantics preserved (oldest first)", assembled.trend.map((t) => t.period), [P1, P2, P3]);
check("period is kept as Ice delivers it -- a Buddhist YYYY-MM string, never converted to a SQL date",
  /^\d{4}-\d{2}$/.test(assembled.period) && !assembled.period.includes("-01"));

console.log("\nunsupported dimensions fail explicitly -- never silently reuse legacy data");
const dataSource = fs.readFileSync("lib/ice-market-data.ts", "utf8");
check("oem_group is not a supported Ice dimension", !/"oem_group"/.test(dataSource.split("§14.3")[1] ?? dataSource));
check("origin_country/market_position/import_type/brand_origin/market_scope have no Ice slicer",
  !/sliceIceBy(OemGroup|MarketPosition|ImportType|OriginCountry|BrandOrigin|MarketScope)/.test(dataSource));

console.log("\nscope guardrails -- never reads the legacy registration engine");
const engineSource = fs.readFileSync("lib/ice-market-engine.ts", "utf8");
const publicSource = fs.readFileSync("lib/ice-public-market.ts", "utf8");
// Checked against actual usage (a Supabase `.from("...")` call, or a real
// call/import clause), not a bare substring -- this file's own module
// docstrings deliberately name these tables/functions to explain why they are
// NOT used, which a plain substring search cannot tell apart from using them.
function stripComments(source: string): string {
  return source.split("\n").filter((line) => !line.trim().startsWith("*") && !line.trim().startsWith("//")).join("\n")
    .replace(/\/\*[\s\S]*?\*\//g, "");
}
for (const [name, source] of [["ice-market-engine.ts", engineSource], ["ice-market-data.ts", dataSource], ["ice-public-market.ts", publicSource]] as const) {
  const code = stripComments(source);
  check(`${name} never reads registration_reporting_source`, !code.includes('"registration_reporting_source"'));
  check(`${name} never reads a registration_* view`, !/\.from\("registration_(brand|model|monthly|chinese)/.test(code));
  check(`${name} never calls sliceMarketFacts (the legacy, mapped-gated slicer)`, !/\bsliceMarketFacts\(/.test(code));
}
check("ice-market-data.ts runs on the service-role credential, never the browser's",
  dataSource.includes("adminDb()") && !dataSource.includes("publicDb()"));
check("M4 does not switch the live /market page to the Ice adapter yet",
  !fs.readFileSync("app/market/page.tsx", "utf8").includes("ice-public-market"));
check("M4 does not switch the live /member/market API route to the Ice engine yet",
  !fs.readFileSync("app/api/report/market/route.ts", "utf8").includes("ice-market-data"));
check("lib/registration-market.ts is untouched by M4 (reused, not modified)",
  !fs.readFileSync("lib/registration-market.ts", "utf8").includes("ice_"));

console.log(failed ? `\n${failed} check(s) failed` : "\nall Ice market engine checks passed");
process.exit(failed ? 1 : 0);
