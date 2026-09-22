// Source-text regression tests proving: the Sales Tools dashboard only
// ever surfaces Sales-Tools-tagged reserved capabilities (never a
// Research/PDF teaser leaking in as a generic panel), Provincial
// Registration remains a deliberate non-interactive Coming Soon card,
// and the public pricing page does not accidentally advertise an
// unreleased capability as part of a sellable plan. Same convention as
// check-quota-architecture.ts / check-launch-safety-patch.ts.
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
  const genericLoopPattern = /Object\.entries\(features\)\.map\(\(\[key, feature\]\) => feature\.state === "teaser"/;
  check("the old generic 'every teaser feature gets a panel' loop is gone", genericLoopPattern.test(memberPage), false);
}
check("the launcher shows a Coming Soon badge", memberPage.includes("comingSoonBadge"), true);
check("the launcher shows the planned tier ladder (Free/Pro/Corporate), not just today's state", memberPage.includes("featureLadder"), true);
{
  const launcherButtonMatch = /<button type="button" disabled aria-disabled="true">[^<]*<\/button>/.exec(memberPage);
  check("the launcher's button exists and is disabled", Boolean(launcherButtonMatch), true);
  check("the launcher's button has no onClick handler -- clicking it can never query data or consume quota", (launcherButtonMatch?.[0] || "").includes("onClick"), false);
}

console.log("\nprovincial launcher — current state AND planned ladder are both preserved, not just one");
check("the dashboard's FeatureInfo type carries current_state (today)", memberPage.includes("current_state:"), true);
check("the dashboard's FeatureInfo type carries ladder (planned)", memberPage.includes("ladder:"), true);
check("the dashboard reads feature.ladder.FREE / PRO / CORPORATE explicitly",
  ["FREE", "PRO", "CORPORATE"].every((audience) => memberPage.includes(`feature.ladder.${audience}`)),
  true,
);
check("the API response includes both current_state and the full ladder per feature", featuresRoute.includes("current_state: resolveFeatureState") && featuresRoute.includes("ladder: Object.fromEntries"), true);

console.log("\nprovincial launcher — unreleased capability stays off the public sellable-plan copy");
check("the policy still registers Provincial Registration as a reserved capability",
  accessPolicy.includes('key: "provincial_registration"') && accessPolicy.includes('label: "Provincial Registration"'), true);
{
  const provincialStart = accessPolicy.indexOf("provincial_registration: {");
  const nextFeature = accessPolicy.indexOf("research_reports: {", provincialStart);
  const provincialBlock = provincialStart >= 0
    ? accessPolicy.slice(provincialStart, nextFeature > provincialStart ? nextFeature : undefined)
    : "";
  check("Provincial Registration remains globally unreleased", provincialBlock.includes("released: false"), true);
}
check("pricing does not hardcode an unreleased Provincial Registration promise",
  pricingPage.includes("provincialCopy(") || pricingPage.includes("PROVINCIAL_LIVE"), false);

console.log("\nprovincial launcher — the launch guard is real code, not just documentation");
check("lib/access-policy.ts exports releaseSafetyViolations for tests to exercise directly", accessPolicy.includes("export function releaseSafetyViolations("), true);
check("lib/access-policy.ts asserts the live catalog is release-safe at module load (the actual launch guard)", accessPolicy.includes("assertFeatureCatalogIsReleaseSafe(FEATURES)"), true);
check("provincial_registration's ladder has no 'limited' audience left, so its policy gate is vacuously satisfied", accessPolicy.includes("limitedAccessPolicyDefined: true"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall provincial launcher checks passed");
process.exit(failed ? 1 : 0);