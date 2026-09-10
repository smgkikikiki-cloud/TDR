import fs from "node:fs";

let failed = 0;
function check(name: string, ok: boolean) {
  if (!ok) { failed++; console.log(`  FAIL ${name}`); }
  else console.log(`  ok   ${name}`);
}
function text(path: string) { return fs.readFileSync(path, "utf8"); }

console.log("admin parity bench — routes stay inside the TDR Admin shell");
for (const path of [
  "app/admin/(secure)/market/page.tsx",
  "app/admin/(secure)/registrations/page.tsx",
  "app/admin/(secure)/prices/page.tsx",
  "app/admin/(secure)/data-quality/page.tsx",
]) check(path, fs.existsSync(path));

const nav = text("components/admin/AdminNav.tsx");
for (const route of ["/admin/market","/admin/registrations","/admin/prices","/admin/data-quality"]) {
  check(`nav exposes ${route}`, nav.includes(`href=\"${route}\"`));
}

const market = text("app/admin/(secure)/market/page.tsx");
check("price band remains blocked until period-aware prices exist", market.includes("WAITING PERIOD PRICE"));
check("legacy retirement blockers are visible", market.includes("Legacy parity blockers"));
const quality = text("app/admin/(secure)/data-quality/page.tsx");
check("data-quality page refuses premature retirement", quality.includes("KEEP LEGACY WORKBENCH"));

const registration = text("app/admin/registration-actions.ts");
check("registration ingest stays on dedicated RPC", registration.includes('rpc("ingest_registration_snapshot"'));
check("registration input does not enter Vehicle Master queue", !registration.includes("canonical_input_batches"));

const parserMigration = text("supabase/migration_v26_registration_snapshot_csv_parser.sql");
check("historical snapshot parser strips UTF-8 BOM", parserMigration.includes("chr(65279)"));
check("historical snapshot parser preserves blank model grain", !parserMigration.includes("or m[4] = ''"));
check("historical snapshot parser accepts commas inside model names", parserMigration.includes("(.*),([0-9]+),([^,]*)$"));
check("historical snapshot parser keeps URL allowlist", parserMigration.includes("snapshot URL is outside the canonical TDR registration snapshot paths"));

const prices = text("app/admin/(secure)/prices/page.tsx");
const priceActions = text("app/admin/price-actions.ts");
check("price history reads canonical projection", prices.includes('canonical_price_projection'));
check("price corrections are not bypassed through serving writes", !prices.includes('.update({ amount_thb'));
check("price maintenance UI is wired", prices.includes("enqueueCorrectPrice") && prices.includes("enqueueClosePrice") && prices.includes("enqueueCampaignUpsert"));
check("price maintenance uses canonical commands", ["CORRECT_PRICE","CLOSE_PRICE","UPSERT_CAMPAIGN"].every((operation) => priceActions.includes(operation)));
check("price maintenance reuses canonical input queue", priceActions.includes("enqueueVehicleInput"));

console.log(failed ? `\n${failed} check(s) failed` : "\nall admin parity smoke checks passed");
process.exit(failed ? 1 : 0);
