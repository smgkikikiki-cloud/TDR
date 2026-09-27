/** Public showroom-lineup surfaces must render only lifecycle-CURRENT
 *  MarketTrim rows from `current_market_trims` -- that table holds every
 *  identity attached to the active canonical release (evidence, research and
 *  historical rows included), not just the ones on sale today. This was the
 *  exact bug behind Volvo EX40's retired trims (Black Edition, Twin Motor
 *  Performance, Extended Range, a duplicate Ultra Single Motor) reappearing
 *  on the model page and in Compare no matter how many times a repair
 *  retired them from the current-retail-set architecture
 *  (automotive/vehicle_master/vehreg/current_retail.py): the new authority
 *  correctly stamps their `market_trims[].status` as UNVERIFIED, but neither
 *  public reader was actually filtering on it.
 *
 *  This repository has no test runner beyond Node's own type stripping
 *  (`npm run check`), and these readers require a live Supabase project, so
 *  the fix is structured to make the DECIDING logic a pure, exported,
 *  directly-testable function (lib/canonical-trim-status.ts) that both
 *  readers call -- rather than something only provable against a live
 *  database or a static source-text guess. */

import { filterToCurrentTrims, isCurrentLifecycleStatus } from "../lib/canonical-trim-status.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

function trim(canonicalId: string, status: string) {
  return { canonical_id: canonicalId, status };
}

console.log("isCurrentLifecycleStatus -- the one rule, strict and case-sensitive");
check("CURRENT is current", isCurrentLifecycleStatus("CURRENT"), true);
check("HISTORICAL is not current", isCurrentLifecycleStatus("HISTORICAL"), false);
check("UNVERIFIED is not current", isCurrentLifecycleStatus("UNVERIFIED"), false);
check("the legacy lowercase 'discontinued' value is not current", isCurrentLifecycleStatus("discontinued"), false);
check("a lowercase 'current' is not silently accepted -- the projector never writes it", isCurrentLifecycleStatus("current"), false);
check("null status is never treated as current", isCurrentLifecycleStatus(null), false);
check("undefined/missing status is never treated as current", isCurrentLifecycleStatus(undefined), false);
check("an unrecognized value is never treated as current", isCurrentLifecycleStatus("SOMETHING_ELSE"), false);

console.log("\nTEST 1 -- model bundle: 1 CURRENT, 2 UNVERIFIED, 1 HISTORICAL -> only the CURRENT trim");
{
  const rows = [
    trim("m.g1.trim.approved", "CURRENT"),
    trim("m.g1.trim.overlay_a", "UNVERIFIED"),
    trim("m.g1.trim.overlay_b", "UNVERIFIED"),
    trim("m.g1.trim.retired", "HISTORICAL"),
  ];
  const result = filterToCurrentTrims(rows);
  check("exactly one trim survives", result.length, 1);
  check("it is the approved one", result[0].canonical_id, "m.g1.trim.approved");
}

console.log("\nTEST 2 -- compare trim loader returns only CURRENT trims");
{
  const rows = [
    trim("m.g1.trim.a", "CURRENT"),
    trim("m.g1.trim.b", "CURRENT"),
    trim("m.g1.trim.c", "HISTORICAL"),
    trim("m.g1.trim.d", "UNVERIFIED"),
  ];
  const result = filterToCurrentTrims(rows);
  check("only the two CURRENT trims survive", result.map((r) => r.canonical_id).sort(), ["m.g1.trim.a", "m.g1.trim.b"]);
}

console.log("\nTEST 3 -- UNVERIFIED overlay identities do not appear in compare options");
{
  const overlayRow = trim("m.g1.trim.black_edition", "UNVERIFIED");
  check("an UNVERIFIED overlay row is rejected on its own", filterToCurrentTrims([overlayRow]).length, 0);
  check("isCurrentLifecycleStatus itself rejects UNVERIFIED", isCurrentLifecycleStatus(overlayRow.status), false);
}

console.log("\nTEST 4 -- HISTORICAL trims do not appear in the current public lineup");
{
  const retiredRow = trim("m.g1.trim.twin_motor", "HISTORICAL");
  check("a HISTORICAL row is rejected", filterToCurrentTrims([retiredRow]).length, 0);
}

console.log("\nTEST 5 -- admin/history/research readers still retain non-current identities (unchanged)");
{
  const fs = await import("node:fs");
  const editor = fs.readFileSync("lib/canonical-editor.ts", "utf8");
  check("the admin Vehicle Editor's trim query is not narrowed to CURRENT -- it must see every identity to manage lifecycle",
    /current_market_trims"\)[\s\S]{0,200}?\.eq\("status",\s*"CURRENT"\)/.test(editor), false);
  const worklist = fs.readFileSync("lib/price-coverage-worklist.ts", "utf8");
  check("the price-coverage admin worklist's own trim query is not narrowed to CURRENT either",
    /current_market_trims"\)[\s\S]{0,200}?\.eq\("status",\s*"CURRENT"\)/.test(worklist), false);
}

console.log("\nTEST 6 -- an unmanaged legacy model's actual CURRENT trims remain fully visible");
{
  const rows = [trim("legacy.g1.trim.a", "CURRENT"), trim("legacy.g1.trim.b", "CURRENT"), trim("legacy.g1.trim.c", "CURRENT")];
  const result = filterToCurrentTrims(rows);
  check("nothing legitimate is excluded when every row really is CURRENT",
    result.map((r) => r.canonical_id).sort(), rows.map((r) => r.canonical_id).sort());
}

console.log("\nTEST 7 -- EX40-shaped case: 7 serving identities, 1 CURRENT, 6 UNVERIFIED -> exactly 1");
{
  const rows = [
    trim("volvo.ex40.gen1.trim.single_ultra_bev", "CURRENT"),
    trim("volvo.ex40.gen1.trim.ultra_single_bev", "UNVERIFIED"),
    trim("volvo.ex40.gen1.trim.ultra_twin_bev", "UNVERIFIED"),
    trim("volvo.ex40.gen1.trim.ultra_twin_black_edition_bev", "UNVERIFIED"),
    trim("volvo.ex40.gen1.trim.black_edition_bev", "UNVERIFIED"),
    trim("volvo.ex40.gen1.trim.twin_performance_bev", "UNVERIFIED"),
    trim("volvo.ex40.gen1.trim.extended_range_bev", "UNVERIFIED"),
  ];
  check("the release still carries all 7 identities (nothing was deleted)", rows.length, 7);
  const result = filterToCurrentTrims(rows);
  check("public lineup result is exactly 1", result.length, 1);
  check("it is the approved EX40 grade", result[0].canonical_id, "volvo.ex40.gen1.trim.single_ultra_bev");
}

console.log("\nwiring -- the two public readers actually use the shared rule, not their own ad-hoc check");
{
  const fs = await import("node:fs");
  const canonicalData = fs.readFileSync("lib/canonical-data.ts", "utf8");
  check("canonical-data.ts imports the shared filter", canonicalData.includes('from "@/lib/canonical-trim-status"'), true);
  check("getCanonicalModelBundle's trim query filters status=CURRENT server-side",
    /current_market_trims"\)\.select\("\*"\)\s*\n\s*\.eq\("model_id", model\.canonical_id\)\.eq\("status", "CURRENT"\)/.test(canonicalData), true);
  check("getCanonicalModelBundle also applies the shared filter in JS (defense in depth)",
    canonicalData.includes("filterToCurrentTrims(rawTrims).map(trimRow)"), true);
  check("getCanonicalCompareTrims's paginated query filters status=CURRENT server-side",
    canonicalData.includes('allRows(db, "current_market_trims", "name", 1000, ["status", "CURRENT"]'), true);
  check("getCanonicalCompareTrims's limited query filters status=CURRENT server-side",
    canonicalData.includes('.eq("status", "CURRENT").order("name").limit(limit)'), true);
  check("getCanonicalCompareTrims applies the shared filter in JS", canonicalData.includes("filterToCurrentTrims(rawTrims)"), true);
  check("the old legacy lowercase 'discontinued' check is gone", canonicalData.includes("discontinued"), false);

  const compareData = fs.readFileSync("lib/compare-canonical-data.ts", "utf8");
  check("compare-canonical-data.ts's isCurrentTrim/isCurrentModel delegate to the same shared rule",
    (compareData.match(/isCurrentLifecycleStatus\(row\?\.status\)/g) || []).length, 2);
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall public trim status checks passed");
process.exit(failed ? 1 : 0);
