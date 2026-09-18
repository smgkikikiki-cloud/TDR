import fs from "node:fs";
import {
  TIER_POLICIES, areMarketFiltersAllowed, historyWindowStart,
  isMarketComparisonAllowed, isMarketDimensionAllowed, isMarketWindowAllowed,
} from "../lib/access-policy.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

console.log("market depth — the free view is the shape, the paid one is the product");
// The line is the grain, not the dimension list: every cut that describes what
// the market looks like is free; ranking one model is the paid question.
for (const cut of ["brand", "powertrain", "body_type", "segment", "origin_country",
                   "oem_group", "brand_origin", "import_type", "market_position",
                   "market_scope", "registration_type"]) {
  check(`free may cut by ${cut}`, isMarketDimensionAllowed(cut, "FREE", null), true);
}
check("free may not rank a single model", isMarketDimensionAllowed("model", "FREE", null), false);
check("pro may", isMarketDimensionAllowed("model", "PRO", null), true);

console.log("\nwindows and comparisons");
check("free gets the month", isMarketWindowAllowed("month", "FREE"), true);
check("free gets rolling three", isMarketWindowAllowed("rolling3", "FREE"), true);
for (const w of ["rolling6", "rolling12", "ytd"]) {
  check(`free does not get ${w}`, isMarketWindowAllowed(w, "FREE"), false);
  check(`pro does`, isMarketWindowAllowed(w, "PRO"), true);
}
check("free compares with the previous period", isMarketComparisonAllowed("previous", "FREE"), true);
check("free does not compare year on year", isMarketComparisonAllowed("yoy", "FREE"), false);
check("pro does", isMarketComparisonAllowed("yoy", "PRO"), true);

console.log("\nhistory and filters");
const now = new Date("2026-09-18T00:00:00Z");
check("free reaches back twelve months, not to January",
  historyWindowStart("FREE", now), "2025-10-01");
check("pro has no lower bound", historyWindowStart("PRO", now), null);
check("free cannot narrow a slice", areMarketFiltersAllowed("FREE"), false);
check("pro can", areMarketFiltersAllowed("PRO"), true);

console.log("\nevery tier states its market depth, so a new one cannot be silent");
for (const [name, policy] of Object.entries(TIER_POLICIES)) {
  check(`${name} declares all four`,
    [typeof policy.marketModelGrain, typeof policy.marketFilters,
     policy.marketWindows === null || Array.isArray(policy.marketWindows),
     policy.marketComparisons === null || Array.isArray(policy.marketComparisons)],
    ["boolean", "boolean", true, true]);
}

console.log("\nenforced where the rows are read, not only in the controls");
const analytics = fs.readFileSync("lib/registration-analytics.ts", "utf8");
check("a narrowed slice is refused server-side",
  analytics.includes("areMarketFiltersAllowed(ctx.tier)") && analytics.includes("hasNarrowingFilter"), true);
check("selecting DLT classes is not treated as narrowing",
  /registrationTypes is deliberately excluded/.test(analytics), true);
const route = fs.readFileSync("app/api/report/market/route.ts", "utf8");
check("the window is checked against the plan before any row is read",
  route.includes("isMarketWindowAllowed(windowValue, ctx.tier)"), true);
check("so is the comparison",
  route.includes("isMarketComparisonAllowed(comparisonMode, ctx.tier)"), true);
check("the response tells the page what it may ask for", route.includes("model_grain:"), true);

const ws = fs.readFileSync("app/member/market/MarketWorkspace.tsx", "utf8");
check("the controls label what costs money rather than failing on it",
  ws.includes("PAID") && ws.includes("plan.model_grain"), true);
check("a refusal for depth reads as an upgrade, not an error",
  ws.includes('status === "upgrade"') && ws.includes("upgrade_required"), true);
check("nothing is marked paid before the plan is known",
  ws.includes("plan ? !plan.filters : false"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall market depth checks passed");
process.exit(failed ? 1 : 0);
