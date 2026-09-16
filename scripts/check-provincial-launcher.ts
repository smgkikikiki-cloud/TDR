// Source-text regression tests proving: the Sales Tools dashboard only
// ever surfaces Sales-Tools-tagged reserved capabilities (never a
// Research/PDF teaser leaking in as a generic panel), the Provincial
// Registration launcher is a deliberate, non-interactive card (no data
// query, no quota consumption), and the pricing page communicates its
// full planned tier ladder -- Coming Soon throughout, no invented
// Individual number -- for Free/Individual/Pro/Corporate alike. Same
// convention as check-quota-architecture.ts / check-launch-safety-patch.ts.
import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const memberPage = fs.readFileSync("app/member/page.tsx", "utf8");
const featuresRoute = fs.readFileSync("app/api/tools/features/route.ts", "utf8");
const pricingPage = fs.readFileSync("app/pricing/page.tsx", "utf8");
const accessPolicy = fs.readFileSync("lib/access-policy.ts", "utf8");

console.log("provincial launcher — the Sales dashboard only surfaces sales_tools-tagged reserved capabilities");
check(
  "the dashboard filters rendered feature panels to surface === 'sales_tools'",
  memberPage.includes('feature.surface === "sales_tools"'),
  true,
);
check(
  "the dashboard also filters to unreleased features only (a released capability would get its own real UI, not a teaser card)",
  memberPage.includes("!feature.released"),
  true,
);
check(
  "the /api/tools/features response carries `surface` so a consumer can filter without re-deriving policy",
  featuresRoute.includes("surface: feature.surface"),
  true,
);

console.log("\nprovincial launcher — a deliberate card, not the old generic loop");
{
  // The old generic implementation rendered a panel for every feature
  // with `state === "teaser"` regardless of what kind of capability it
  // was -- that string must be gone from the dashboard's render logic.
  const genericLoopPattern = /Object\.entries\(features\)\.map\(\(\[key, feature\]\) => feature\.state === "teaser"/;
  check("the old generic 'every teaser feature gets a panel' loop is gone", genericLoopPattern.test(memberPage), false);
}
check("the launcher shows a Coming Soon badge", memberPage.includes("comingSoonBadge"), true);
check("the launcher shows the planned tier ladder (Free/Individual/Pro/Corporate), not just today's state", memberPage.includes("featureLadder"), true);
{
  const launcherButtonMatch = /<button type="button" disabled aria-disabled="true">[^<]*<\/button>/.exec(memberPage);
  check("the launcher's button exists and is disabled", Boolean(launcherButtonMatch), true);
  check("the launcher's button has no onClick handler -- clicking it can never query data or consume quota", (launcherButtonMatch?.[0] || "").includes("onClick"), false);
}

console.log("\nprovincial launcher — current state AND planned ladder are both preserved, not just one");
check("the dashboard's FeatureInfo type carries current_state (today)", memberPage.includes("current_state:"), true);
check("the dashboard's FeatureInfo type carries ladder (planned)", memberPage.includes("ladder:"), true);
check("the dashboard reads feature.ladder.FREE / INDIVIDUAL / PRO / CORPORATE explicitly",
  ["FREE", "INDIVIDUAL", "PRO", "CORPORATE"].every((audience) => memberPage.includes(`feature.ladder.${audience}`)),
  true,
);
check("the API response includes both current_state and the full ladder per feature", featuresRoute.includes("current_state: resolveFeatureState") && featuresRoute.includes("ladder: Object.fromEntries"), true);

console.log("\nprovincial launcher — pricing page adds Provincial Registration to all four audiences, Coming Soon throughout");
check("Free card includes the provincial line", pricingPage.includes('provincialCopy("FREE")'), true);
check("Individual card includes the provincial line", pricingPage.includes('provincialCopy("INDIVIDUAL")'), true);
check("Pro card includes the provincial line", pricingPage.includes('provincialCopy("PRO")'), true);
check("Corporate section includes the provincial line", pricingPage.includes('provincialCopy("CORPORATE")'), true);
check(
  "provincialCopy always appends '(Coming Soon)' while the feature is unreleased",
  pricingPage.includes("PROVINCIAL_LIVE") && pricingPage.includes("(Coming Soon)"),
  true,
);
check(
  "the Individual ladder label does not hardcode a numeric limit -- it stays a qualitative 'Limited (TBD)' label",
  /limited:\s*"Limited \(รายละเอียดยังไม่กำหนด\)"/.test(pricingPage) && !/limited.*\d+\s*(ครั้ง|จังหวัด|province)/i.test(pricingPage),
  true,
);

console.log("\nprovincial launcher — the launch guard is real code, not just documentation");
check("lib/access-policy.ts exports releaseSafetyViolations for tests to exercise directly", accessPolicy.includes("export function releaseSafetyViolations("), true);
check("lib/access-policy.ts asserts the live catalog is release-safe at module load (the actual launch guard)", accessPolicy.includes("assertFeatureCatalogIsReleaseSafe(FEATURES)"), true);
check("provincial_registration's Individual 'limited' policy is explicitly marked undefined today", accessPolicy.includes("limitedAccessPolicyDefined: false"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall provincial launcher checks passed");
process.exit(failed ? 1 : 0);
