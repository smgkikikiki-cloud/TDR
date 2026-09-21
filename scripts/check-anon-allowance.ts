import fs from "node:fs";
import {
  ANON_COMPARE_DAILY_LIMIT, ANON_MARKET_DAILY_LIMIT, allowanceFrom, bangkokDayKey,
  encodeCount, readCount,
} from "../lib/anon-allowance.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

console.log("anonymous allowance — a real trial, then an account");
check("ten comparisons a day before signing up", ANON_COMPARE_DAILY_LIMIT, 10);
check("one market view a day", ANON_MARKET_DAILY_LIMIT, 1);

check("a fresh reader has used nothing", readCount(undefined, "2026-09-18"), 0);
check("a count is read back", readCount(encodeCount("2026-09-18", 3), "2026-09-18"), 3);
// Yesterday's count is not today's: a scope that does not match has
// expired, and expiry must read as zero rather than as a carried-over total.
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

console.log("\nwiring — the gate is where the data is, not only in the UI");
const route = fs.readFileSync("app/api/tools/compare/route.ts", "utf8");
check("an anonymous comparison is served rather than refused",
  route.includes("anonymousComparison") && !route.includes('if (!accessToken) return NextResponse.json({ error: "sign in'), true);
check("the table itself is built once for both callers",
  (route.match(/buildComparison\(/g) || []).length >= 3, true);
check("spending the allowance writes the cookie back", route.includes("response.cookies.set("), true);
check("the compare cookie resets daily, same as market -- not a lifetime total",
  route.includes("bangkokDayKey()") && !route.includes('"life"'), true);

const mw = fs.readFileSync("middleware.ts", "utf8");
check("the market view is counted on the server, before the page renders",
  mw.includes('matcher: ["/market"]') && mw.includes("x-tdr-market-remaining"), true);
check("a signed-in reader is not counted at all", mw.includes("if (signedIn) return"), true);

const market = fs.readFileSync("app/market/page.tsx", "utf8");
check("what is covered is the real page, not a picture of one",
  market.includes("marketLockBody") && market.includes("<MarketCharts"), true);
check("the blurred copy is hidden from assistive technology",
  market.includes('aria-hidden="true"'), true);

const policy = fs.readFileSync("lib/access-policy.ts", "utf8");
const free = policy.slice(policy.indexOf("FREE: {"), policy.indexOf("PRO: {"));
check("an account removes the comparison limit", /compareDailyLimit: null/.test(free), true);
check("five market queries a day", /salesQueryDailyLimit: 5/.test(free), true);
check("two full analyses a month", /researchFullMonthlyLimit: 2/.test(free), true);
check("one export a month", /pdfMonthlyLimit: 1/.test(free), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall anonymous allowance checks passed");
process.exit(failed ? 1 : 0);
