// Source-text regression tests proving the quota architecture's structural
// invariants (matching this repo's existing check-*.ts convention of
// reading real source files and asserting on their text -- see
// scripts/check-member-market.ts's price/trend checks). These exist
// because the actual concurrency fix (pg_advisory_xact_lock in
// tdr_consume_usage, see migration_v34) cannot be exercised against a
// live Postgres from this test suite; what CAN be verified without one is
// that quota is only ever consumed from exactly the intended call sites,
// never from a lower-level helper that could be invoked more than once
// per logical action, and that there is no client-supplied action id left
// anywhere in the contract for a client to bypass quota with.
import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

function occurrences(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

const registrationAnalytics = fs.readFileSync("lib/registration-analytics.ts", "utf8");
const marketRoute = fs.readFileSync("app/api/report/market/route.ts", "utf8");
const dashboardRoute = fs.readFileSync("app/api/tools/sales-dashboard/route.ts", "utf8");
const compareRoute = fs.readFileSync("app/api/tools/compare/route.ts", "utf8");
const registrationRoute = fs.readFileSync("app/api/report/registration/route.ts", "utf8");
const accessPolicyServer = fs.readFileSync("lib/access-policy-server.ts", "utf8");

console.log("quota architecture — lower-level fetchers never consume quota themselves");
function functionBody(source: string, signature: string): string {
  const start = source.indexOf(signature);
  if (start === -1) throw new Error(`signature not found: ${signature}`);
  // Find the matching closing brace for the function body by depth count,
  // starting from the first "{" after the signature.
  const braceStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}") {
      depth--;
      if (depth === 0) return source.slice(braceStart, i + 1);
    }
  }
  throw new Error(`unbalanced braces for: ${signature}`);
}

const marketSliceFn = functionBody(registrationAnalytics, "export async function getRegistrationMarketSlice(");
check("getRegistrationMarketSlice never calls requireUsage", marketSliceFn.includes("requireUsage"), false);
check("getRegistrationMarketSlice never calls consumeSalesQueryQuota", marketSliceFn.includes("consumeSalesQueryQuota"), false);

const fetchDimensionFn = functionBody(registrationAnalytics, "async function fetchDimensionRowsInternal(");
check("fetchDimensionRowsInternal never calls requireUsage", fetchDimensionFn.includes("requireUsage"), false);
check("fetchDimensionRowsInternal never calls consumeSalesQueryQuota", fetchDimensionFn.includes("consumeSalesQueryQuota"), false);

console.log("\nquota architecture — each top-level action consumes quota exactly once");
const dashboardFn = functionBody(registrationAnalytics, "export async function getRegistrationDashboard(");
check("getRegistrationDashboard calls consumeSalesQueryQuota exactly once", occurrences(dashboardFn, "consumeSalesQueryQuota("), 1);
check(
  "getRegistrationDashboard fetches every permitted dimension AFTER that single quota call, not before",
  dashboardFn.indexOf("consumeSalesQueryQuota(") < dashboardFn.indexOf("allowedDimensions.map"),
  true,
);

check("the market route calls consumeMarketReportQuota exactly once", occurrences(marketRoute, "await consumeMarketReportQuota("), 1);
check(
  "the market route's quota call happens before it fetches current/previous/trend rows",
  marketRoute.indexOf("consumeMarketReportQuota(") < marketRoute.indexOf("marketSliceWithPrice({\n      ctx,\n      dimension: dimensionValue,"),
  true,
);

console.log("\nquota architecture — no client-supplied action id anywhere in the contract");
// Checks for an actual functional read/send of the header, not any
// mention of its old name in an explanatory comment (several routes and
// pages document, in prose, that this header used to exist and why it
// was removed -- that's documentation, not a regression).
const HEADER_READ = /headers\.get\(\s*["']x-tdr-action-id["']\s*\)/i;
const HEADER_SEND = /["']x-tdr-action-id["']\s*:/i;
const clientFacingFiles: Record<string, string> = {
  "lib/registration-analytics.ts": registrationAnalytics,
  "app/api/report/market/route.ts": marketRoute,
  "app/api/tools/sales-dashboard/route.ts": dashboardRoute,
  "app/api/tools/compare/route.ts": compareRoute,
  "app/api/report/registration/route.ts": registrationRoute,
};
for (const [path, source] of Object.entries(clientFacingFiles)) {
  check(`${path} never reads the X-TDR-Action-Id header`, HEADER_READ.test(source), false);
}
const memberPage = fs.readFileSync("app/member/page.tsx", "utf8");
const marketWorkspace = fs.readFileSync("app/member/market/MarketWorkspace.tsx", "utf8");
check("the member dashboard page never sends an X-TDR-Action-Id header", HEADER_SEND.test(memberPage), false);
check("the market workspace page never sends an X-TDR-Action-Id header", HEADER_SEND.test(marketWorkspace), false);

console.log("\nquota architecture — the dashboard is one HTTP request, not a client-side fan-out");
check("member dashboard calls the composite /api/tools/sales-dashboard endpoint", memberPage.includes("/api/tools/sales-dashboard"), true);
check("member dashboard no longer fans out to /api/report/registration per dimension", memberPage.includes("/api/report/registration"), false);
// "oem_group" itself is no longer a safe marker for the old fan-out: it is
// now also a legitimate ranking-dimension option in the filter picker
// (OEM Group). What actually matters is that loadMarket() -- the function
// one "Update market" click runs -- still makes exactly one jsonFetch call,
// not a per-dimension/per-period loop; the trend fan-out this section is
// about was already proven gone by the two checks above (trend is computed
// server-side and returned in that same response).
const loadMarketFn = functionBody(marketWorkspace, "async function loadMarket(");
check("loadMarket makes exactly one HTTP request per Update-market click, not a per-dimension fan-out",
  occurrences(loadMarketFn, "jsonFetch("), 1);

console.log("\nquota architecture — fingerprint is computed inside requireUsage/consumeUsage, callers only pass semantic parts");
const requireUsageFn = functionBody(accessPolicyServer, "export async function requireUsage(");
const consumeUsageFn = functionBody(accessPolicyServer, "export async function consumeUsage(");
check("consumeUsage calls requestFingerprint itself (callers never compute it)", consumeUsageFn.includes("requestFingerprint("), true);
check("requireUsage never accepts a raw action id parameter", requireUsageFn.includes("actionId"), false);

console.log(failed ? `\n${failed} check(s) failed` : "\nall quota architecture checks passed");
process.exit(failed ? 1 : 0);
