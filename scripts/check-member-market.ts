import fs from "node:fs";
import { normalizeRequestedMarketScopes } from "../lib/market-scope.ts";
import { defaultMarketPeriod, provisionalMarketPeriods } from "../lib/member-market.ts";
import {
  MARKET_PRICE_MIN_COVERAGE_PCT,
  marketPriceBandForAmount,
  resolveListPriceOn,
  resolveModelPriceBand,
  type MarketPriceState,
} from "../lib/market-price-state.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

console.log("paid market — scope contract");
check("no scope request defaults to CORE plus honest mixed-grain residual", normalizeRequestedMarketScopes(), ["CORE", "MIXED"]);
check("explicit all scopes removes the scope filter", normalizeRequestedMarketScopes(["all"]), undefined);
check("explicit scope stays normalized and keeps mixed residual", normalizeRequestedMarketScopes(["niche", "core", "core"]), ["NICHE", "CORE", "MIXED"]);

console.log("\npaid market — provisional month default");
const coverage = [
  ["2026-01-01", 100], ["2026-02-01", 110], ["2026-03-01", 90],
  ["2026-04-01", 105], ["2026-05-01", 95], ["2026-06-01", 100],
  ["2026-07-01", 20],
].map(([period, total]) => ({ period: String(period), total_registrations: Number(total) }));
check("stub month is labelled provisional", [...provisionalMarketPeriods(coverage)], ["2026-07"]);
check("workspace opens on latest settled month", defaultMarketPeriod(coverage), "2026-06");

console.log("\npaid market — period price contract");
check("price band lower edge", marketPriceBandForAmount(499_999), "ENTRY");
check("price band volume", marketPriceBandForAmount(500_000), "VOLUME");
check("price band upper", marketPriceBandForAmount(1_000_000), "UPPER");
check("price band luxury starts at 1.8m", marketPriceBandForAmount(1_800_000), "LUXURY");
check("paid price cohort minimum is fail-closed at 80%", MARKET_PRICE_MIN_COVERAGE_PCT, 80);

const observedOnly = [{
  trim_id: "m.g.t1", amount_thb: 900_000, price_type: "LIST_PRICE",
  effective_from: null, effective_to: null, observed_at: "2026-09-08", payload: {},
}];
check("observed-only list price is never backcast", resolveListPriceOn(observedOnly, "2026-08-31"), null);
check("observed-only list price starts on observation date", resolveListPriceOn(observedOnly, "2026-09-30"), 900_000);
check("campaign price never defines MSRP cohort", resolveListPriceOn([{ ...observedOnly[0], price_type: "CAMPAIGN_PRICE", amount_thb: 599_000 }], "2026-09-30"), null);
check("conflicting list prices at the same canonical start fail closed", resolveListPriceOn([
  observedOnly[0], { ...observedOnly[0], amount_thb: 950_000 },
], "2026-09-30"), null);

const fakeState: MarketPriceState = {
  releaseId: "test",
  trimsByModel: new Map([
    ["single", [{ trimId: "single.t1", generationId: "g1" }]],
    ["mixed", [{ trimId: "mixed.t1", generationId: "g1" }, { trimId: "mixed.t2", generationId: "g1" }]],
    ["partial", [{ trimId: "partial.t1", generationId: "g1" }, { trimId: "partial.t2", generationId: "g1" }]],
  ]),
  generations: new Map([["g1", { launched: "2020-01-01", ended: null }]]),
  listPricesByTrim: new Map([
    ["single.t1", [{ ...observedOnly[0], trim_id: "single.t1" }]],
    ["mixed.t1", [{ ...observedOnly[0], trim_id: "mixed.t1", amount_thb: 900_000 }]],
    ["mixed.t2", [{ ...observedOnly[0], trim_id: "mixed.t2", amount_thb: 1_100_000 }]],
    ["partial.t1", [{ ...observedOnly[0], trim_id: "partial.t1", amount_thb: 900_000 }]],
  ]),
};
check("one verified band resolves model cohort", resolveModelPriceBand(fakeState, "single", "2026-09"), "VOLUME");
check("cross-band model is MIXED rather than guessed", resolveModelPriceBand(fakeState, "mixed", "2026-09"), "MIXED");
check("missing active trim price makes model UNKNOWN", resolveModelPriceBand(fakeState, "partial", "2026-09"), "UNKNOWN");

console.log("\npaid market — trend keeps the full selected scope");
const workspace = fs.readFileSync("app/member/market/MarketWorkspace.tsx", "utf8");
check("trend uses a neutral non-UI dimension so Brand/Model/Segment/Body/Powertrain filters stay closed", workspace.includes('marketPath(trendFilters, period, 1, false, "oem_group")'), true);
check("trend helper can override ranking dimension without changing applied filter state", workspace.includes('dimension: string = filters.dimension'), true);

console.log("\npaid market — price API stays canonical and fail-closed");
const marketApi = fs.readFileSync("app/api/report/market/route.ts", "utf8");
check("API accepts explicit canonical price band", marketApi.includes('searchParams.get("price_band")'), true);
check("API reads active canonical price state", marketApi.includes("getActiveMarketPriceState"), true);
check("API blocks low verified price coverage", marketApi.includes("verified canonical LIST_PRICE coverage is too low"), true);
check("API does not use legacy models table as a price fallback", marketApi.includes('from("models")'), false);
check("rolling price cohorts stay blocked until fact-month slicing is supported", marketApi.includes("price-band filtering is currently month-grain only"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall member market checks passed");
process.exit(failed ? 1 : 0);