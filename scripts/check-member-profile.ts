/**
 * What one profile save does, case by case.
 *
 * These run the decision the route runs (lib/profile-update.ts) over real
 * inputs and real stored rows, and assert the columns it would write. The
 * HTTP layer and the upsert around it are not exercised here.
 */
import { planProfileUpdate } from "../lib/profile-update.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

const NOW = "2026-09-21T00:00:00.000Z";
const V = "2026-01";
const plan = (body: Record<string, unknown>, existing: any = null) =>
  planProfileUpdate(body, existing, NOW, V);

const COMPLETE_INDIVIDUAL = {
  postcode: "10110", is_individual: true, company_name: null,
  profile_completed_at: "2026-09-01T00:00:00.000Z",
};

console.log("A — a member fills in only their postcode");
{
  const p = plan({ postcode: "10110" }, { is_individual: true });
  check("the postcode is written", p.changes.postcode, "10110");
  check("nothing else is touched", Object.keys(p.changes).sort(),
    ["postcode", "profile_completed_at"]);
  check("an individual with a postcode is complete", p.profileComplete);
  check("and it is stamped, once", p.changes.profile_completed_at, NOW);
}

console.log("\nB — a member ticks the marketing box and nothing else");
{
  const p = plan({ marketing_consent: true }, { is_individual: true, postcode: null });
  check("consent is recorded with its version",
    [p.changes.marketing_consent, p.changes.marketing_consent_version], [true, V]);
  check("the postcode is not invented", "postcode" in p.changes, false);
  // Ticking a box is not filling in a profile. The old route stamped
  // profile_completed_at on any edit, so the funnel counted this as a
  // completed profile.
  check("a profile with no postcode is not complete", p.profileComplete, false);
  check("and nothing is stamped", "profile_completed_at" in p.changes, false);
}

console.log("\nC — a member says they are a company");
{
  const p = plan({ is_individual: false, company_name: " TDR Co., Ltd. " },
    { postcode: "10110", is_individual: true });
  check("the company name is trimmed and kept", p.changes.company_name, "TDR Co., Ltd.");
  check("the account is no longer an individual", p.changes.is_individual, false);
  check("a company with a name and a postcode is complete", p.profileComplete);
}

console.log("\nD — a company account says it is an individual after all");
{
  const p = plan({ is_individual: true },
    { postcode: "10110", is_individual: false, company_name: "TDR Co., Ltd." });
  // The company name belongs to a company account. Clearing it is the
  // edit, not a side effect of an unrelated one.
  check("the company name is cleared", p.changes.company_name, null);
  check("the account is complete as an individual", p.profileComplete);
}

console.log("\nE — a company with no name is not complete");
{
  const p = plan({ is_individual: false, company_name: "   " }, { postcode: "10110" });
  check("an empty company name is stored as nothing", p.changes.company_name, null);
  check("and the profile is not complete", p.profileComplete, false);
  check("so nothing is stamped", "profile_completed_at" in p.changes, false);
}

console.log("\nF — a request that asks for nothing changes nothing");
{
  const p = plan({}, COMPLETE_INDIVIDUAL);
  check("no column is written", Object.keys(p.changes), []);
  check("the save reports that it saved nothing", p.touched, false);
}

console.log("\nthe edges the cases above imply");
{
  const bad = plan({ postcode: "abc" }, null);
  check("a postcode that is not a postcode is refused", bad.error, "postcode must be 4-10 digits");
  check("and nothing is written on the way out", Object.keys(bad.changes), []);

  const cleared = plan({ postcode: "" }, COMPLETE_INDIVIDUAL);
  check("clearing a postcode is an edit, and writes null", cleared.changes.postcode, null);
  check("the profile is no longer complete", cleared.profileComplete, false);
  // The stamp records when it was first true. Nothing gates on it -- the
  // gate that matters (lib/access-policy-server.ts) recomputes.
  check("the earlier completion is not re-stamped or erased",
    "profile_completed_at" in cleared.changes, false);

  const again = plan({ postcode: "10230" }, COMPLETE_INDIVIDUAL);
  check("a later edit to a complete profile does not re-stamp it",
    "profile_completed_at" in again.changes, false);

  const withdrawn = plan({ marketing_consent: false }, COMPLETE_INDIVIDUAL);
  check("withdrawing consent writes the false", withdrawn.changes.marketing_consent, false);
  check("and does not re-date the consent", "marketing_consent_at" in withdrawn.changes, false);
}

console.log("\nG — the exact blocker case: is_individual alone must not erase the company");
{
  // Literal case, do not alter: an existing company account, a request
  // that names only is_individual (already false), and company_name must
  // survive untouched. The earlier bug collapsed
  // `sent("company_name") || sent("is_individual")` into one branch, so
  // sending is_individual at all -- even unchanged, even false -- blanked
  // company_name to "" and wrote null over "Toyota Thailand".
  const existing = {
    postcode: "10110", is_individual: false, company_name: "Toyota Thailand",
    profile_completed_at: "2026-09-01T00:00:00.000Z",
  };
  const p = plan({ is_individual: false }, existing);
  check("company_name is not in the write at all -- this is the bug", "company_name" in p.changes, false);
  check("postcode is untouched", "postcode" in p.changes, false);
  check("marketing_consent is untouched", "marketing_consent" in p.changes, false);
  // is_individual itself is written (presence-is-an-edit, same rule as
  // postcode) even though the value matches what is already stored --
  // that mirrors the request. company_name is the only column the old
  // code wrongly dragged along with it.
  check("only is_individual is written, not company_name too",
    Object.keys(p.changes), ["is_individual"]);
  check("profile stays complete (a company with its name and postcode)", p.profileComplete);
  check("completion is not re-stamped", "profile_completed_at" in p.changes, false);
}

console.log("\nH — postcode-only edit on the same company account preserves company");
{
  const existing = {
    postcode: "10110", is_individual: false, company_name: "Toyota Thailand",
    profile_completed_at: "2026-09-01T00:00:00.000Z",
  };
  const p = plan({ postcode: "10330" }, existing);
  check("only postcode is written", Object.keys(p.changes), ["postcode"]);
  check("company_name survives", p.profileComplete);
}

console.log("\nI — withdrawing marketing consent on the same account preserves company");
{
  const existing = {
    postcode: "10110", is_individual: false, company_name: "Toyota Thailand",
    profile_completed_at: "2026-09-01T00:00:00.000Z",
  };
  const p = plan({ marketing_consent: false }, existing);
  check("only marketing_consent is written", Object.keys(p.changes), ["marketing_consent"]);
  check("company_name is not touched", "company_name" in p.changes, false);
}

console.log("\nJ — declaring individual on a company account clears the name");
{
  const existing = {
    postcode: "10110", is_individual: false, company_name: "Toyota Thailand",
    profile_completed_at: "2026-09-01T00:00:00.000Z",
  };
  const p = plan({ is_individual: true }, existing);
  check("company_name is explicitly cleared", p.changes.company_name, null);
  check("is_individual flips", p.changes.is_individual, true);
}

console.log("\nK — an empty body changes no domain field");
{
  const existing = {
    postcode: "10110", is_individual: false, company_name: "Toyota Thailand",
    profile_completed_at: "2026-09-01T00:00:00.000Z",
  };
  const p = plan({}, existing);
  check("nothing is written", Object.keys(p.changes), []);
  check("the save reports nothing touched", p.touched, false);
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall member profile checks passed");
process.exit(failed ? 1 : 0);
