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

const prices = text("app/admin/(secure)/prices/page.tsx");
check("price history reads canonical projection", prices.includes('canonical_price_projection'));
check("price corrections are not bypassed through serving writes", !prices.includes('.update({ amount_thb'));

console.log(failed ? `\n${failed} check(s) failed` : "\nall admin parity smoke checks passed");
process.exit(failed ? 1 : 0);
