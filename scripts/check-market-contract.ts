import {
  compareMarketSliceRows,
  comparisonMarketWindow,
  isMarketDimension,
  missingReportPeriods,
  normalizeReportPeriod,
  periodRangeLabel,
  resolveMarketWindow,
  shiftReportPeriod,
  sliceMarketFacts,
  type CanonicalRegistrationFact,
  type MarketSliceRow,
} from "../lib/registration-market.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else {
    console.log(`  ok   ${name}`);
  }
}

console.log("registration market periods — calendar windows never jump across gaps");
check("normalize YYYY-MM", normalizeReportPeriod("2026-08"), "2026-08-01");
check("reject impossible month", normalizeReportPeriod("2026-13"), null);
check("shift across year boundary", shiftReportPeriod("2026-01", -1), "2025-12-01");
check("rolling three months", resolveMarketWindow("2026-08", "rolling3"), {
  from: "2026-06-01", to: "2026-08-01",
});
check("YTD window", resolveMarketWindow("2026-08", "ytd"), {
  from: "2026-01-01", to: "2026-08-01",
});
check("previous non-overlapping rolling window",
  comparisonMarketWindow(resolveMarketWindow("2026-08", "rolling3"), "previous"),
  { from: "2026-03-01", to: "2026-05-01" });
check("same window last year",
  comparisonMarketWindow(resolveMarketWindow("2026-08", "rolling3"), "yoy"),
  { from: "2025-06-01", to: "2025-08-01" });
check("missing month is explicit, never silently skipped",
  missingReportPeriods(
    { from: "2026-06-01", to: "2026-08-01" },
    ["2026-06-01", "2026-08-01"],
  ),
  ["2026-07-01"]);

console.log("\nperiod range label — only formats the backend's own resolved window, never re-derives it");
check("single month has no dash", periodRangeLabel("2026-08-01", "2026-08-01"), "ส.ค. 2569");
check("multi-month window shows the effective range", periodRangeLabel("2026-08-01", "2026-10-01"), "ส.ค. 2569–ต.ค. 2569");
check("range crossing a year boundary carries each Buddhist-era year", periodRangeLabel("2025-11-01", "2026-01-01"), "พ.ย. 2568–ม.ค. 2569");
check("YTD window (Jan through the anchor month)", periodRangeLabel("2026-01-01", "2026-08-01"), "ม.ค. 2569–ส.ค. 2569");
check("missing bound yields no label rather than a guess", periodRangeLabel(null, "2026-08-01"), "");

console.log("\nregistration market dimensions — only supported canonical facets enter the contract");
check("model is supported", isMarketDimension("model"), true);
check("price is deliberately not live yet", isMarketDimension("price_band"), false);
check("arbitrary SQL-ish token is rejected", isMarketDimension("model;drop table"), false);

function fact(overrides: Partial<CanonicalRegistrationFact>): CanonicalRegistrationFact {
  return {
    period: "2026-08-01",
    registration_type: "RY1",
    registrations: 0,
    canonical_model_id: null,
    canonical_brand_id: null,
    brand_name: "UNKNOWN",
    model_name: "UNKNOWN",
    segment: "UNKNOWN",
    body_type: "UNKNOWN",
    powertrain: "UNKNOWN",
    oem_group: "UNKNOWN",
    market_position: "Mass",
    import_type: "UNKNOWN",
    origin_country: "UNKNOWN",
    brand_origin: "UNKNOWN",
    market_scope: "CORE",
    raw_brand_name: "",
    raw_model_name: "",
    brand_mapped: false,
    canonically_mapped: false,
    ...overrides,
  };
}

const marketFacts: CanonicalRegistrationFact[] = [
  fact({
    registrations: 60, canonical_model_id: "model-a", canonical_brand_id: "brand-a",
    brand_name: "Brand A", model_name: "Model A", segment: "C", body_type: "CROSSOVER",
    powertrain: "BEV", oem_group: "Group A", brand_origin: "TH",
    brand_mapped: true, canonically_mapped: true,
  }),
  fact({
    registrations: 40, canonical_model_id: "model-b", canonical_brand_id: "brand-b",
    brand_name: "Brand B", model_name: "Model B", segment: "C", body_type: "CROSSOVER",
    powertrain: "HEV", oem_group: "Group B", brand_origin: "JP",
    brand_mapped: true, canonically_mapped: true,
  }),
  fact({
    registrations: 20, canonical_model_id: "model-c", canonical_brand_id: "brand-c",
    brand_name: "Brand C", model_name: "Model C", segment: "D", body_type: "SEDAN",
    powertrain: "ICE", oem_group: "Group C", brand_origin: "DE",
    brand_mapped: true, canonically_mapped: true,
  }),
  fact({
    registrations: 10, canonical_brand_id: "brand-a", brand_name: "Brand A",
    raw_brand_name: "BRAND A", raw_model_name: "UNRESOLVED LABEL", oem_group: "Group A",
    brand_origin: "TH", brand_mapped: true, canonically_mapped: false,
  }),
];

console.log("\nmarket slicer — preserve competitive denominator and honest grain");
const brandRanking = sliceMarketFacts({
  facts: marketFacts,
  dimension: "brand",
  filters: { brandIds: ["brand-a"] },
  limit: 10,
});
check("ranking dimension opens its own filter", brandRanking.map((row) => row.entity_key), ["brand-a", "brand-b", "brand-c"]);
check("brand-grain residual stays in Brand A", Number(brandRanking[0]?.registrations), 70);
check("brand market keeps honest residual volume", Number(brandRanking[0]?.market_total), 130);
check("coverage still reports model mapping, not fake perfection", Number(brandRanking[0]?.window_mapping_coverage_pct), 92.3);

const modelInsideBrand = sliceMarketFacts({
  facts: marketFacts,
  dimension: "model",
  filters: { brandIds: ["brand-a"] },
  limit: 10,
});
check("brand filter narrows a model ranking", modelInsideBrand.map((row) => row.entity_key), ["model-a"]);
check("brand-only residual is never invented as a model", Number(modelInsideBrand[0]?.market_total), 60);

const segmentRanking = sliceMarketFacts({
  facts: marketFacts,
  dimension: "segment",
  filters: { segments: ["C"] },
  limit: 10,
});
check("segment ranking opens segment scope", segmentRanking.map((row) => row.entity_key), ["C", "D"]);
check("model-dependent dimension excludes brand-only residual", Number(segmentRanking[0]?.market_total), 120);

const previous: MarketSliceRow[] = [
  {
    entity_key: "a", entity_label: "A", registrations: 40, market_total: 100,
    market_share_pct: 40, market_rank: 1, window_raw_units: 100,
    window_mapped_units: 100, window_mapping_coverage_pct: 100,
  },
  {
    entity_key: "b", entity_label: "B", registrations: 35, market_total: 100,
    market_share_pct: 35, market_rank: 2, window_raw_units: 100,
    window_mapped_units: 100, window_mapping_coverage_pct: 100,
  },
];
const current: MarketSliceRow[] = [
  {
    entity_key: "a", entity_label: "A", registrations: 36, market_total: 120,
    market_share_pct: 30, market_rank: 2, window_raw_units: 120,
    window_mapped_units: 120, window_mapping_coverage_pct: 100,
  },
  {
    entity_key: "b", entity_label: "B", registrations: 60, market_total: 120,
    market_share_pct: 50, market_rank: 1, window_raw_units: 120,
    window_mapped_units: 120, window_mapping_coverage_pct: 100,
  },
  {
    entity_key: "c", entity_label: "C", registrations: 24, market_total: 120,
    market_share_pct: 20, market_rank: 3, window_raw_units: 120,
    window_mapped_units: 120, window_mapping_coverage_pct: 100,
  },
];
const movement = compareMarketSliceRows(previous, current);

console.log("\nshare movement — market position, not raw unit delta, drives ordering");
check("largest share gainer leads", movement.map((row) => row.entity_key), ["c", "b", "a"]);
check("B gains 15 percentage points", movement.find((row) => row.entity_key === "b")?.share_change_pp, 15);
check("B climbs one rank", movement.find((row) => row.entity_key === "b")?.rank_change, 1);
check("new entrant has no fake previous rank", movement.find((row) => row.entity_key === "c")?.rank_previous, null);
check("A can lose units and share separately", {
  units: movement.find((row) => row.entity_key === "a")?.units_change,
  share: movement.find((row) => row.entity_key === "a")?.share_change_pp,
}, { units: -4, share: -10 });

console.log(failed ? `\n${failed} check(s) failed` : "\nall market contract checks passed");
process.exit(failed ? 1 : 0);
