import fs from "node:fs";
import {
  ANON_COMPARE_DAILY_LIMIT, allowanceFrom, bangkokDayKey,
  encodeCount, readCount,
} from "../lib/anon-allowance.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

console.log("anonymous allowance — browse freely, meter real actions");
check("ten comparisons a day before signing up", ANON_COMPARE_DAILY_LIMIT, 10);

check("a fresh reader has used nothing", readCount(undefined, "2026-09-18"), 0);
check("a count is read back", readCount(encodeCount("2026-09-18", 3), "2026-09-18"), 3);
check("another day's count does not carry over", readCount(encodeCount("2026-09-17", 1), "2026-09-18"), 0);
check("a tampered value is not trusted", readCount("2026-09-18.-5", "2026-09-18"), 0);
check("neither is a non-number", readCount("2026-09-18.abc", "2026-09-18"), 0);
check("nor a value with no scope", readCount("4", "2026-09-18"), 0);

const ninth = allowanceFrom(encodeCount("2026-09-18", 9), "2026-09-18", ANON_COMPARE_DAILY_LIMIT);
check("the tenth comparison is still allowed", ninth.exhausted, false);
check("and it is the last one", ninth.remaining, 1);
const tenth = allowanceFrom(encodeCount("2026-09-18", 10), "2026-09-18", ANON_COMPARE_DAILY_LIMIT);
check("the eleventh is not", tenth.exhausted, true);
check("remaining never goes negative", allowanceFrom(encodeCount("2026-09-18", 99), "2026-09-18", ANON_COMPARE_DAILY_LIMIT).remaining, 0);

check("the day key is the Thai calendar day",
  bangkokDayKey(new Date("2026-09-18T17:30:00Z")), "2026-09-19");
check("and rolls at Thai midnight, not UTC",
  bangkokDayKey(new Date("2026-09-18T16:59:00Z")), "2026-09-18");

console.log("\nwiring — page views are free; analysis actions are metered");
const compareRoute = fs.readFileSync("app/api/tools/compare/route.ts", "utf8");
check("an anonymous comparison is served rather than refused",
  compareRoute.includes("anonymousComparison") && !compareRoute.includes('if (!accessToken) return NextResponse.json({ error: "sign in'), true);
check("spending the compare allowance writes its cookie back", compareRoute.includes("response.cookies.set("), true);
check("the compare cookie resets daily, not as a lifetime total",
  compareRoute.includes("bangkokDayKey()") && !compareRoute.includes('"life"'), true);

check("there is no middleware left to count /market page requests", !fs.existsSync("middleware.ts"), true);

const market = fs.readFileSync("app/market/page.tsx", "utf8");
check("opening the public market does not read an allowance header",
  !market.includes("x-tdr-market-remaining") && !market.includes("headers()"), true);
check("the public market has no exhausted/blurred page-view lock",
  !market.includes("marketLock") && !market.includes("ดูฟรีได้วันละ 1 ครั้ง"), true);
check("the public snapshot always renders the real chart",
  market.includes('getPublicMarket("brand")') && market.includes("<MarketCharts"), true);
check("analysis starts in the member market rather than through public query params",
  market.includes('href="/member/market"') && !market.includes("searchParams"), true);

const memberMarketRoute = fs.readFileSync("app/api/report/market/route.ts", "utf8");
check("member market analysis requires a bearer session",
  memberMarketRoute.includes("member bearer token required"), true);
check("member market analysis consumes quota at the action boundary",
  memberMarketRoute.includes("consumeMarketReportQuota"), true);

const policy = fs.readFileSync("lib/access-policy.ts", "utf8");
const free = policy.slice(policy.indexOf("FREE: {"), policy.indexOf("PRO: {"));
check("an account removes the comparison limit", /compareDailyLimit: null/.test(free), true);
check("five market analyses a day", /salesQueryDailyLimit: 5/.test(free), true);
check("two full analyses a month", /researchFullMonthlyLimit: 2/.test(free), true);
check("one export a month", /pdfMonthlyLimit: 1/.test(free), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall anonymous allowance checks passed");
process.exit(failed ? 1 : 0);
