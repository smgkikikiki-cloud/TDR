import {
  currentSalesModuleCycleKey,
  dailyPeriodKey,
  FEATURES,
  featuresForSurface,
  historyWindowStart,
  isMarketDimensionAllowed,
  isPeriodWithinHistoryWindow,
  isRegistrationDimensionAllowed,
  monthlyPeriodKey,
  releaseSafetyViolations,
  resetsAtForMetric,
  resolveFeatureState,
  resolveTierFromEntitlements,
  SALES_MODULES,
  validateSalesModuleSelection,
  type EntitlementRow,
  type FeatureDefinition,
  type FeatureKey,
} from "../lib/access-policy.ts";
import { requestFingerprint } from "../lib/request-fingerprint.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

console.log("access policy — tier resolution");
check("no entitlement rows -> FREE", resolveTierFromEntitlements([]), "FREE");
check(
  "legacy registration_full ACTIVE -> PRO (backward compatibility)",
  resolveTierFromEntitlements([{ product: "registration_full", status: "ACTIVE", valid_until: null }] as EntitlementRow[]),
  "PRO",
);
check(
  "legacy registration_full GRACE -> still PRO",
  resolveTierFromEntitlements([{ product: "registration_full", status: "GRACE", valid_until: null }] as EntitlementRow[]),
  "PRO",
);
check(
  "expired legacy registration_full -> FREE",
  resolveTierFromEntitlements([{ product: "registration_full", status: "ACTIVE", valid_until: "2020-01-01T00:00:00Z" }] as EntitlementRow[]),
  "FREE",
);
check(
  "tier_individual ACTIVE -> INDIVIDUAL",
  resolveTierFromEntitlements([{ product: "tier_individual", status: "ACTIVE", valid_until: null }] as EntitlementRow[]),
  "INDIVIDUAL",
);
check(
  "tier_pro beats tier_individual when both present",
  resolveTierFromEntitlements([
    { product: "tier_individual", status: "ACTIVE", valid_until: null },
    { product: "tier_pro", status: "ACTIVE", valid_until: null },
  ] as EntitlementRow[]),
  "PRO",
);
check(
  "REVOKED status never grants access",
  resolveTierFromEntitlements([{ product: "tier_pro", status: "REVOKED", valid_until: null }] as EntitlementRow[]),
  "FREE",
);

console.log("\naccess policy — Asia/Bangkok cycle keys");
// 2026-01-01T16:59:59Z is 2026-01-01 23:59:59 Bangkok (UTC+7) -- still Jan 1.
check("daily key just before Bangkok midnight", dailyPeriodKey(new Date("2026-01-01T16:59:59Z")), "2026-01-01");
// One second later it is 2026-01-02 00:00:00 Bangkok.
check("daily key rolls over at Bangkok midnight", dailyPeriodKey(new Date("2026-01-01T17:00:00Z")), "2026-01-02");
check("monthly key matches Bangkok month", monthlyPeriodKey(new Date("2026-01-31T20:00:00Z")), "2026-02");
check("sales module cycle key = calendar month (policy default)", currentSalesModuleCycleKey(new Date("2026-03-15T00:00:00Z")), "2026-03");

console.log("\naccess policy — quota resets_at");
check(
  "daily reset is the next Bangkok midnight in UTC",
  resetsAtForMetric("vehicle_compare", new Date("2026-01-01T10:00:00Z")),
  new Date("2026-01-01T17:00:00.000Z").toISOString(),
);
check(
  "monthly reset is the 1st of next Bangkok month in UTC",
  resetsAtForMetric("research_full", new Date("2026-02-15T10:00:00Z")),
  new Date("2026-02-28T17:00:00.000Z").toISOString(),
);

console.log("\naccess policy — history window enforcement");
check("Pro has no history floor", historyWindowStart("PRO", new Date("2026-06-15T00:00:00Z")), null);
// Free was clamped to the calendar year, which made January a cliff: on the
// 1st a reader lost eleven months of context overnight. A rolling twelve is
// the same amount of history on every day of the year.
check("Free reaches back twelve rolling months", historyWindowStart("FREE", new Date("2026-06-15T00:00:00Z")), "2025-07-01");
check("Individual gets a 24-month rolling floor", historyWindowStart("INDIVIDUAL", new Date("2026-06-15T00:00:00Z")), "2024-07-01");
check("period inside Free's window is allowed", isPeriodWithinHistoryWindow("FREE", "2026-03-01", new Date("2026-06-15T00:00:00Z")), true);
check("period before Free's window is rejected", isPeriodWithinHistoryWindow("FREE", "2025-06-01", new Date("2026-06-15T00:00:00Z")), false);
check("a period inside the rolling year is allowed even though it is last year", isPeriodWithinHistoryWindow("FREE", "2025-12-01", new Date("2026-06-15T00:00:00Z")), true);

console.log("\naccess policy — sales module selection + dimension gating");
check("exactly 4 known modules validates", validateSalesModuleSelection(["brand_share", "model_share", "month_on_month", "segment_share"], 4), null);
check("wrong count is rejected", validateSalesModuleSelection(["brand_share"], 4) !== null, true);
check("unknown module is rejected", validateSalesModuleSelection(["brand_share", "model_share", "month_on_month", "not_a_module"], 4) !== null, true);
check("duplicate module is rejected", validateSalesModuleSelection(["brand_share", "brand_share", "month_on_month", "segment_share"], 4) !== null, true);

check("coverage dimension is always allowed on Free (boot metadata, not a module)", isRegistrationDimensionAllowed("coverage", "FREE", null), true);
check("unselected dimension is blocked on Free", isRegistrationDimensionAllowed("brand", "FREE", ["model_share"]), false);
check("selected dimension is allowed on Free", isRegistrationDimensionAllowed("brand", "FREE", ["brand_share"]), true);
check("every dimension is allowed on Pro regardless of selection", isRegistrationDimensionAllowed("brand", "PRO", null), true);

// Market depth no longer runs through the 4-of-6 module picker: the line is
// the grain. Every cut that describes the shape of the market is free, and
// only ranking an individual model is reserved -- module selection does not
// change that, which is exactly what the next two assert.
check("selecting model_share does not buy Free the model grain", isMarketDimensionAllowed("model", "FREE", ["model_share"]), false);
check("market dimension mapped to an unselected module is blocked on Free", isMarketDimensionAllowed("model", "FREE", ["brand_share"]), false);
check("a structural cut is free whether or not a module was picked", isMarketDimensionAllowed("oem_group", "FREE", []), true);
check("market dimension with no module mapping is allowed on Individual/Pro", isMarketDimensionAllowed("oem_group", "INDIVIDUAL", null), true);

console.log("\naccess policy — reserved capabilities (provincial_registration)");
check("unreleased feature resolves to teaser for Free", resolveFeatureState("provincial_registration", "FREE"), "teaser");
check("unreleased feature resolves to teaser for Individual too (global kill switch)", resolveFeatureState("provincial_registration", "INDIVIDUAL"), "teaser");
check("unreleased feature resolves to teaser for Pro too (global kill switch)", resolveFeatureState("provincial_registration", "PRO"), "teaser");
check("unreleased feature resolves to teaser for Corporate too (global kill switch)", resolveFeatureState("provincial_registration", "CORPORATE"), "teaser");
check("provincial_registration is not part of the 4-of-6 sales module catalog", (SALES_MODULES as readonly string[]).includes("provincial_registration"), false);
check("provincial_registration never counts toward sales module selection", FEATURES.provincial_registration.countsTowardSalesModuleSelection, false);
check("provincial_registration never consumes quota", FEATURES.provincial_registration.consumesQuota, false);
check("provincial_registration is not released yet", FEATURES.provincial_registration.released, false);

console.log("\naccess policy — server-computed quota fingerprint (no client-trusted action id)");
const T0 = 1_800_000_000_000; // fixed instant, same coalesce bucket for T0 and T0+1000ms at a 5s window
check(
  "identical request retried a moment later coalesces to the same fingerprint",
  requestFingerprint("user-1", "sales_query", ["dashboard", "2026-06-01", "brand,model"], 5000, T0)
    === requestFingerprint("user-1", "sales_query", ["dashboard", "2026-06-01", "brand,model"], 5000, T0 + 1000),
  true,
);
check(
  "a materially different request (different dimension set) never coalesces, even at the same instant",
  requestFingerprint("user-1", "sales_query", ["dashboard", "2026-06-01", "brand,model"], 5000, T0)
    === requestFingerprint("user-1", "sales_query", ["dashboard", "2026-06-01", "segment,powertrain"], 5000, T0),
  false,
);
check(
  "a different user never shares a fingerprint for the identical request",
  requestFingerprint("user-1", "sales_query", ["dashboard", "2026-06-01", "brand,model"], 5000, T0)
    === requestFingerprint("user-2", "sales_query", ["dashboard", "2026-06-01", "brand,model"], 5000, T0),
  false,
);
check(
  "the same request well outside the coalesce window pays fresh quota (not an infinite free pass)",
  requestFingerprint("user-1", "vehicle_compare", ["a,b", false], 5000, T0)
    === requestFingerprint("user-1", "vehicle_compare", ["a,b", false], 5000, T0 + 60_000),
  false,
);
check(
  "compare selection order does not matter once the caller sorts ids, but an actually different selection differs",
  requestFingerprint("user-1", "vehicle_compare", [["a", "b"].sort().join(","), false], 5000, T0)
    === requestFingerprint("user-1", "vehicle_compare", [["a", "c"].sort().join(","), false], 5000, T0),
  false,
);

console.log("\naccess policy — Sales Tools surface filtering (reserved capabilities)");
check(
  "provincial_registration is surfaced on sales_tools (eligible for the Sales dashboard's launcher card)",
  FEATURES.provincial_registration.surface,
  "sales_tools",
);
check("research_reports is NOT surfaced on sales_tools", FEATURES.research_reports.surface !== "sales_tools", true);
check("pdf_export_reports is NOT surfaced on sales_tools", FEATURES.pdf_export_reports.surface !== "sales_tools", true);
check(
  "featuresForSurface('sales_tools') returns exactly provincial_registration today",
  featuresForSurface("sales_tools").map((f) => f.key),
  ["provincial_registration"],
);
check(
  "featuresForSurface('research') and ('pdf_export') never include provincial_registration",
  featuresForSurface("research").some((f) => f.key === "provincial_registration")
    || featuresForSurface("pdf_export").some((f) => f.key === "provincial_registration"),
  false,
);

console.log("\naccess policy — launch guard: released cannot ship an undecided 'limited' policy");
check("the live FEATURES catalog has zero release-safety violations (this also proves the module-load guard didn't throw)", releaseSafetyViolations(), []);

function fixtureFeature(overrides: Partial<FeatureDefinition>): Record<FeatureKey, FeatureDefinition> {
  const base: FeatureDefinition = {
    key: "provincial_registration",
    label: "Test Feature",
    labelTh: "ทดสอบ",
    surface: "sales_tools",
    released: false,
    stateByAudience: { FREE: "teaser", INDIVIDUAL: "limited", PRO: "full", CORPORATE: "tailored" },
    countsTowardSalesModuleSelection: false,
    consumesQuota: false,
    limitedAccessPolicyDefined: false,
    ...overrides,
  };
  return { provincial_registration: base } as Record<FeatureKey, FeatureDefinition>;
}

check(
  "released=true + a 'limited' audience + limitedAccessPolicyDefined=false IS flagged as a violation",
  releaseSafetyViolations(fixtureFeature({ released: true, limitedAccessPolicyDefined: false })).length > 0,
  true,
);
check(
  "released=true + a 'limited' audience + limitedAccessPolicyDefined=true is NOT flagged",
  releaseSafetyViolations(fixtureFeature({ released: true, limitedAccessPolicyDefined: true })),
  [],
);
check(
  "released=false is never flagged regardless of limitedAccessPolicyDefined (the kill switch already forces teaser for everyone)",
  releaseSafetyViolations(fixtureFeature({ released: false, limitedAccessPolicyDefined: false })),
  [],
);
check(
  "released=true with NO 'limited' audience anywhere in the ladder is never flagged, even with limitedAccessPolicyDefined=false",
  releaseSafetyViolations(fixtureFeature({
    released: true,
    limitedAccessPolicyDefined: false,
    stateByAudience: { FREE: "teaser", INDIVIDUAL: "full", PRO: "full", CORPORATE: "tailored" },
  })),
  [],
);

console.log(failed ? `\n${failed} check(s) failed` : "\nall access policy checks passed");
process.exit(failed ? 1 : 0);
