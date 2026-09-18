import fs from "node:fs";
import { groupedNumber, compactNumber } from "../components/charts/format.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

const lib = fs.readFileSync("lib/public-market.ts", "utf8");
const page = fs.readFileSync("app/market/page.tsx", "utf8");

console.log("public market — the opening in the paywall stays the size it was cut");
// Registration data answers the browser's own key with 401, so this module is
// the one deliberate way any of it reaches an anonymous reader. These hold the
// shape of that opening; widening it should have to be a decision, not a diff.
check("it runs on the server credential, never the browser's", lib.includes("adminDb()"));
check("brand grain only — no model, trim or segment cut",
  /dimension: "brand"/.test(lib) && !/dimension: "(model|trim|segment|body_type)"/.test(lib));
check("the window is the latest published month, never a caller's choice",
  lib.includes("latestPublishedPeriod") && !/window:\s*args\./.test(lib));
check("the named ranking is capped", lib.includes("PUBLIC_BRAND_LIMIT"));
check("the tail is folded into one bucket rather than published", lib.includes("แบรนด์อื่น") || page.includes("แบรนด์อื่น"));
check("the trend is a total, not a per-brand series",
  lib.includes('key: "total"') || fs.readFileSync("app/market/MarketCharts.tsx", "utf8").includes('key: "total"'));
check("no export path is offered from the public page",
  !/export|download|csv/i.test(page.replace(/export default|export const/g, "")));
check("the page says what is behind the account", page.includes("/member/market"));

console.log("\nnumbers — identical on the server and in the browser");
// A client component is rendered twice: once in Node, once in the browser.
// toLocaleString resolves against whatever ICU each has, and one different
// character makes React throw the subtree away.
check("grouping is done here, not by the runtime's locale data",
  !/toLocaleString/.test(fs.readFileSync("app/market/MarketCharts.tsx", "utf8")));
check("thousands", groupedNumber(54318), "54,318");
check("millions", groupedNumber(1234567), "1,234,567");
check("under a thousand is ungrouped", groupedNumber(742), "742");
check("negatives keep their sign outside the grouping", groupedNumber(-1130), "-1,130");
check("fractions are kept when asked for", groupedNumber(30.249, 1), "30.2");
check("compact for an axis", compactNumber(54318), "54k");
check("compact leaves small numbers alone", compactNumber(742), "742");
check("a non-number is a dash, not NaN", groupedNumber(Number.NaN), "—");

console.log("\ncharts — the marks say what the data says");
const donut = fs.readFileSync("components/charts/PieChart.tsx", "utf8");
const line = fs.readFileSync("components/charts/LineChart.tsx", "utf8");
check("arc coordinates are rounded, so server and client agree character for character",
  donut.includes("value.toFixed(3)"));
check("a line does not force a zero baseline", !/Math\.min\(0,/.test(line));
check("a missing month breaks the line instead of being interpolated",
  line.includes('`${open ? "L" : "M"}'));
check("every chart carries a text alternative",
  donut.includes('role="img"') && line.includes('role="img"'));

console.log(failed ? `\n${failed} check(s) failed` : "\nall public market checks passed");
process.exit(failed ? 1 : 0);
