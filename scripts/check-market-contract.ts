import {
  compareMarketSliceRows,
  comparisonMarketWindow,
  isMarketDimension,
  missingReportPeriods,
  normalizeReportPeriod,
  resolveMarketWindow,
  shiftReportPeriod,
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

console.log("\nregistration market dimensions — only supported canonical facets enter the RPC");
check("model is supported", isMarketDimension("model"), true);
check("price is deliberately not live yet", isMarketDimension("price_band"), false);
check("arbitrary SQL-ish token is rejected", isMarketDimension("model;drop table"), false);

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
