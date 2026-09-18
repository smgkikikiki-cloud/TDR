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
  "app/admin/(secure)/eco-trims/page.tsx",
  "app/admin/(secure)/data-quality/page.tsx",
]) check(path, fs.existsSync(path));

const nav = text("components/admin/AdminNav.tsx");
for (const route of ["/admin/market","/admin/registrations","/admin/prices","/admin/eco-trims","/admin/data-quality"]) {
  check(`nav exposes ${route}`, nav.includes(`href=\"${route}\"`));
}

const market = text("app/admin/(secure)/market/page.tsx");
check("price band remains blocked until period-aware prices exist", market.includes("WAITING PERIOD PRICE"));
check("legacy retirement blockers are visible", market.includes("Legacy parity blockers"));
const quality = text("app/admin/(secure)/data-quality/page.tsx");
check("data-quality page refuses premature retirement", quality.includes("KEEP LEGACY WORKBENCH"));
check("data-quality exposes ECO MarketTrim workflow separately from coverage", quality.includes("ECO → MarketTrim review workflow"));
check("price range gate uses registration-weighted canonical coverage", quality.includes("priceCoverage.registrationCoveragePct3m >= 80"));
check("price range gate does not use model seed price fields", !quality.includes("retail_price_min") && !quality.includes("retail_price_max"));
check("data-quality links operator to ECO review", quality.includes('href="/admin/eco-trims"'));

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

// Editing a car is one job. It had two front doors -- the editor and the raw
// input queue -- sitting side by side in a flat sixteen-item list, which is
// what made the admin unreadable. These checks hold the hierarchy in place.
const home = text("app/admin/(secure)/page.tsx");
const inputPage = text("app/admin/(secure)/vehicle-input/page.tsx");
check("the editor is the sidebar's one primary entry", nav.includes('className="adminNavPrimary" href="/admin/vehicles"'));
check("raw input is not a top-level sibling of the editor",
  nav.indexOf('href="/admin/vehicle-input"') > nav.indexOf("adminNavGroup"));
check("industry and editorial forms are not top-level",
  ["/admin/plants/new", "/admin/companies/new", "/admin/events/new"]
    .every((route) => nav.indexOf(`href="${route}"`) > nav.indexOf("Industry &amp; editorial")));
check("the daily queues stay reachable without opening a group",
  ["/admin/prices", "/admin/prices/coverage", "/admin/retail-lifecycle", "/admin/eco-trims",
   "/admin/registrations", "/admin/data-quality"]
    .every((route) => nav.indexOf(`href="${route}"`) < nav.indexOf("adminNavGroup")));
check("the admin home leads with editing a car", home.includes('className="adminPrimaryLink" href="/admin/vehicles"'));
check("the home tiles are queues, not a second way to author a vehicle",
  !home.includes('href="/admin/vehicle-input"'));
check("raw input says what it is for instead of claiming to be the one door",
  !inputPage.includes("แก้ข้อมูลรถจากจุดเดียว") && inputPage.includes("Raw canonical input"));
check("raw input points at the editor for ordinary work",
  inputPage.includes('href="/admin/vehicles"'));

console.log(failed ? `\n${failed} check(s) failed` : "\nall admin parity smoke checks passed");
process.exit(failed ? 1 : 0);
