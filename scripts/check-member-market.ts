import { normalizeRequestedMarketScopes } from "../lib/market-scope.ts";
import { defaultMarketPeriod, provisionalMarketPeriods } from "../lib/member-market.ts";

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

console.log(failed ? `\n${failed} check(s) failed` : "\nall member market checks passed");
process.exit(failed ? 1 : 0);
