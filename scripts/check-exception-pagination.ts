/**
 * Exception work-list pagination -- wiring guards.
 *
 * The 1200-row acceptance case (page 1 visible, page 2/next retrieves the
 * remainder, count is exact, resolving an item on a later page works) is
 * proved against a real Postgres table of that exact size in
 * automotive/vehicle_master/tests/test_exception_pagination_migration_v43.py,
 * which runs the same keyset SQL listOpenExceptionsPage() builds through
 * PostgREST. These are the structural guarantees that keep the UI honest
 * about what it is showing.
 */
import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

const lib = fs.readFileSync("lib/import-exceptions.ts", "utf8");
console.log("lib/import-exceptions.ts");
{
  check("the old bare .limit(1000)-is-the-work-list function is gone",
    !lib.includes("export async function listOpenExceptions("));
  check("pagination is keyset (created_at, id), not OFFSET",
    lib.includes('.order("created_at", { ascending: false })')
      && lib.includes('.order("id", { ascending: false })')
      && !lib.includes(".range("));
  check("a page asks for an exact total count, not an estimate",
    lib.includes('{ count: "exact", head: true }'));
  check("registration gaps are read from the grouped DB view, not grouped in memory",
    lib.includes('from("import_run_registration_gaps")')
      && !lib.includes("gaps.set(key,"));
  check("the grouped view read has no .limit below what the DB itself can hold",
    !/import_run_registration_gaps[\s\S]{0,300}?\.limit\(\d{1,3}\)/.test(lib));
}

const v43 = fs.readFileSync("supabase/migration_v43_exception_pagination.sql", "utf8");
console.log("\nmigration_v43");
{
  check("the registration-gap view groups over every OPEN row, no LIMIT in its definition",
    v43.includes("create or replace view public.import_run_registration_gaps")
      && !/import_run_registration_gaps[\s\S]*?group by 1, 2, 3;[\s\S]{0,50}limit/i.test(v43));
  check("it is scoped to OPEN registration-identity rows only",
    v43.includes("where status = 'OPEN'") && v43.includes("kind = 'REGISTRATION_IDENTITY'"));
}

const page = fs.readFileSync("app/admin/(secure)/exceptions/page.tsx", "utf8");
console.log("\nthe exceptions page");
{
  check("it fetches a page through the paginated reader, not the old whole-list one",
    page.includes("listOpenExceptionsPage(") && !page.includes("listOpenExceptions("));
  check("it shows the exact total and a next/prev (load-more-equivalent) control",
    page.includes("page.total") && page.includes("nextChain") && page.includes("prevChain"));
  check("registration gaps come from the ungrouped-by-page reader",
    page.includes("listRegistrationGaps("));
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall exception pagination checks passed");
process.exit(failed ? 1 : 0);
