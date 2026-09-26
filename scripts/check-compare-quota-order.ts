import fs from "node:fs";

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

const route = fs.readFileSync("app/api/tools/compare/route.ts", "utf8");

console.log("compare quota — validate selection before charging usage");

const resolveAt = route.indexOf("selected = (await getCanonicalCompareTrimsByIds(requestedIds))");
const invalidAt = route.indexOf("if (selected.length !== requestedIds.length)");
const allowanceAt = route.indexOf("const allowance = allowanceFrom(");
const quotaAt = route.indexOf("const quota = await requireUsage(");

check("selected trims are resolved", resolveAt >= 0, true);
check("missing/stale trim IDs are rejected", invalidAt >= 0, true);
check("selection resolves before invalid-selection validation", resolveAt < invalidAt, true);
check("invalid-selection validation happens before anonymous allowance lookup", invalidAt < allowanceAt, true);
check("invalid-selection validation happens before member quota usage", invalidAt < quotaAt, true);
check("invalid selection is a 400 and keeps the missing_selection signal",
  route.includes('error: "one or more selected trims are unavailable"')
    && route.includes("missing_selection: requestedIds.length !== selected.length")
    && /missing_selection:\s*requestedIds\.length !== selected\.length,[\s\S]{0,100}\}, \{ status: 400 \}/.test(route), true);

const selectionCalls = route.match(/getCanonicalCompareTrimsByIds\(requestedIds\)/g) || [];
check("canonical selected trims are fetched exactly once per request", selectionCalls.length, 1);
check("comparison builder consumes pre-resolved trims instead of IDs",
  route.includes("function buildComparison(selected: FreeCompareTrim[], diffOnly: boolean)"), true);
check("anonymous response consumes the same pre-resolved trims",
  route.includes("function anonymousComparison(selected: FreeCompareTrim[], diffOnly: boolean, remaining: number)"), true);
check("successful comparisons explicitly report no missing selection",
  route.includes("missing_selection: false"), true);

const cookieWriteAt = route.indexOf("response.cookies.set(");
check("anonymous allowance cookie is only written after selection validation",
  invalidAt < cookieWriteAt, true);
check("member quota is only charged after selection validation",
  invalidAt < quotaAt, true);

console.log(failed ? `\n${failed} compare quota-order check(s) failed` : "\nall compare quota-order checks passed");
process.exit(failed ? 1 : 0);
