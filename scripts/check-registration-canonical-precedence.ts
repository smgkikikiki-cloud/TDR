/**
 * Registration canonical id precedence, at the TS layer.
 *
 * The DB-level acceptance scenario (a row with no legacy model_id, mapped
 * only through canonical_model_id, coverage and unmapped-detection both
 * correct) is proved against real Postgres in
 * automotive/vehicle_master/tests/test_registration_canonical_precedence_migration_v42.py.
 * This is the precedence rule itself, run directly, plus the wiring
 * guards that keep lib/admin-registration-market.ts using it instead of
 * growing a second copy.
 */
import fs from "node:fs";
import { resolveCanonicalModelId, isRegistrationMapped } from "../lib/registration-canonical-resolve.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

const crosswalk = (legacyId: string) => (legacyId === "legacy-1" ? "toyota.yaris" : null);

console.log("precedence");
{
  check("canonical_model_id on the row wins outright",
    resolveCanonicalModelId({ canonicalModelId: "newbrand.newmodel", legacyModelId: null }, crosswalk),
    "newbrand.newmodel");
  check("a legacy model_id falls back through the reverse crosswalk",
    resolveCanonicalModelId({ canonicalModelId: null, legacyModelId: "legacy-1" }, crosswalk),
    "toyota.yaris");
  check("both null is unresolved",
    resolveCanonicalModelId({ canonicalModelId: null, legacyModelId: null }, crosswalk), null);
  check("a legacy id the crosswalk does not know is unresolved",
    resolveCanonicalModelId({ canonicalModelId: null, legacyModelId: "legacy-unknown" }, crosswalk), null);
  check("canonical_model_id wins even when the legacy id points somewhere else",
    resolveCanonicalModelId({ canonicalModelId: "newbrand.newmodel", legacyModelId: "legacy-1" }, crosswalk),
    "newbrand.newmodel");
}

console.log("\nmapped means either half resolves, not model_id alone");
{
  check("the acceptance case -- no legacy row at all -- is mapped",
    isRegistrationMapped({ canonicalModelId: "newbrand.newmodel", legacyModelId: null }, crosswalk));
  check("a genuinely unmapped row is not",
    isRegistrationMapped({ canonicalModelId: null, legacyModelId: null }, crosswalk), false);
}

console.log("\nwiring: the consumers named in the audit use this rule, not their own");
{
  const marketLib = fs.readFileSync("lib/admin-registration-market.ts", "utf8");
  check("canonicalize() calls the shared precedence rule",
    marketLib.includes("resolveCanonicalModelId("));
  check("the registrations query now selects canonical_model_id, not just model_id",
    marketLib.includes("model_id,canonical_model_id,registrations"));
  check("unmapped detection requires BOTH ids null, not model_id alone",
    marketLib.includes('.is("model_id", null).is("canonical_model_id", null)'));
  check("the old model_id-only unmapped test is gone",
    !/\.is\("model_id", null\)\.order/.test(marketLib));

  const v42 = fs.readFileSync("supabase/migration_v42_registration_canonical_precedence.sql", "utf8");
  check("registration_reporting_source passes registrations.canonical_model_id through before falling back",
    v42.includes("coalesce(r.canonical_model_id, cvm.canonical_id) as canonical_model_id"));
  check("registration_analytics_coverage counts mapped by canonical_model_id, not model_id",
    v42.includes("filter(where r.canonical_model_id is not null)")
      && !v42.includes("filter(where r.model_id is not null)"));
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall registration canonical precedence checks passed");
process.exit(failed ? 1 : 0);
