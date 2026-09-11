import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const helper = fs.readFileSync("lib/price-coverage-worklist.ts", "utf8");
const page = fs.readFileSync("app/admin/(secure)/prices/coverage/page.tsx", "utf8");
const nav = fs.readFileSync("components/admin/AdminNav.tsx", "utf8");

console.log("price coverage worklist — canonical trust boundary");
check("current price requires amount_thb, so JSON null is not counted", helper.includes("current_list_price?.amount_thb"), true);
check("catalog seed values are read only as separate hints", helper.includes("variantSeedPrices"), true);
check("seed hint never feeds pricedTrims", /pricedTrims = trims\.filter\(\(trim\) => actualCurrentPrice\(trim\) != null\)\.length/.test(helper), true);
check("readiness requires every MarketTrim priced", helper.includes("row.totalTrims > 0 && row.missingTrims === 0"), true);
check("worklist is prioritized by registration impact", helper.includes("b.registrations3m - a.registrations3m"), true);
check("registration mapping uses canonical model tdr_model_id bridge", helper.includes("unitsByTdrModel.get(String(model.tdr_model_id"), true);
check("OEM target signal comes from price-intelligence registry", helper.includes("pricefeed/targets.json"), true);

console.log("\nprice coverage worklist — operator UX");
check("page labels seeds unverified", page.includes("UNVERIFIED seed hint"), true);
check("page says seed is not authority", page.includes("ไม่ใช่ authority"), true);
check("page shows registration weighted coverage", page.includes("3M registration coverage"), true);
check("page states the 80% paid gate", page.includes("80%"), true);
check("admin navigation exposes the worklist", nav.includes('href="/admin/prices/coverage"'), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall price coverage worklist checks passed");
process.exit(failed ? 1 : 0);
