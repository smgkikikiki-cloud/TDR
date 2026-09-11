import {
  isCatalogVisible,
  isHistorical,
  isVerifiedCurrent,
  publicCompatibilityStatus,
  publicRetailLifecycle,
} from "../lib/public-retail-lifecycle.ts";

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

console.log("public retail lifecycle — fail closed");
check("canonical CURRENT is trusted", publicRetailLifecycle("CURRENT"), "CURRENT");
check("legacy lowercase current is not trusted", publicRetailLifecycle("current"), "UNVERIFIED");
check("missing lifecycle is unverified", publicRetailLifecycle(null), "UNVERIFIED");
check("unknown lifecycle is unverified", publicRetailLifecycle("ACTIVE"), "UNVERIFIED");
check("canonical HISTORICAL is historical", publicRetailLifecycle("HISTORICAL"), "HISTORICAL");
check("legacy discontinued stays historical", publicRetailLifecycle("discontinued"), "HISTORICAL");
check("only exact CURRENT is verified current", [isVerifiedCurrent("CURRENT"), isVerifiedCurrent("current"), isVerifiedCurrent("UNVERIFIED")], [true, false, false]);
check("historical is excluded from main catalogue", [isCatalogVisible("CURRENT"), isCatalogVisible("UNVERIFIED"), isCatalogVisible("HISTORICAL")], [true, true, false]);
check("historical helper recognizes canonical and legacy", [isHistorical("HISTORICAL"), isHistorical("discontinued"), isHistorical("UNVERIFIED")], [true, true, false]);
check("compatibility never maps unverified to current", [publicCompatibilityStatus("CURRENT"), publicCompatibilityStatus("HISTORICAL"), publicCompatibilityStatus("current")], ["CURRENT", "discontinued", "UNVERIFIED"]);

console.log(failed ? `\n${failed} check(s) failed` : "\nall public retail lifecycle checks passed");
process.exit(failed ? 1 : 0);
