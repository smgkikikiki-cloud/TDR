import {
  currentSalesModuleCycleKey,
  dailyPeriodKey,
  historyWindowStart,
  isMarketDimensionAllowed,
  isPeriodWithinHistoryWindow,
  isRegistrationDimensionAllowed,
  monthlyPeriodKey,
  resetsAtForMetric,
  resolveTierFromEntitlements,
  validateSalesModuleSelection,
  type EntitlementRow,
} from "../lib/access-policy.ts";

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
check("Free is clamped to the current Bangkok calendar year", historyWindowStart("FREE", new Date("2026-06-15T00:00:00Z")), "2026-01-01");
check("Individual gets a 24-month rolling floor", historyWindowStart("INDIVIDUAL", new Date("2026-06-15T00:00:00Z")), "2024-07-01");
check("period inside Free's window is allowed", isPeriodWithinHistoryWindow("FREE", "2026-03-01", new Date("2026-06-15T00:00:00Z")), true);
check("period before Free's window is rejected", isPeriodWithinHistoryWindow("FREE", "2025-12-01", new Date("2026-06-15T00:00:00Z")), false);

console.log("\naccess policy — sales module selection + dimension gating");
check("exactly 4 known modules validates", validateSalesModuleSelection(["brand_share", "model_share", "month_on_month", "segment_share"], 4), null);
check("wrong count is rejected", validateSalesModuleSelection(["brand_share"], 4) !== null, true);
check("unknown module is rejected", validateSalesModuleSelection(["brand_share", "model_share", "month_on_month", "not_a_module"], 4) !== null, true);
check("duplicate module is rejected", validateSalesModuleSelection(["brand_share", "brand_share", "month_on_month", "segment_share"], 4) !== null, true);

check("coverage dimension is always allowed on Free (boot metadata, not a module)", isRegistrationDimensionAllowed("coverage", "FREE", null), true);
check("unselected dimension is blocked on Free", isRegistrationDimensionAllowed("brand", "FREE", ["model_share"]), false);
check("selected dimension is allowed on Free", isRegistrationDimensionAllowed("brand", "FREE", ["brand_share"]), true);
check("every dimension is allowed on Pro regardless of selection", isRegistrationDimensionAllowed("brand", "PRO", null), true);

check("market dimension mapped to a selected module is allowed on Free", isMarketDimensionAllowed("model", "FREE", ["model_share"]), true);
check("market dimension mapped to an unselected module is blocked on Free", isMarketDimensionAllowed("model", "FREE", ["brand_share"]), false);
check("market dimension with no module mapping is paid-tier-only on Free", isMarketDimensionAllowed("oem_group", "FREE", ["brand_share", "model_share", "segment_share", "powertrain_share"]), false);
check("market dimension with no module mapping is allowed on Individual/Pro", isMarketDimensionAllowed("oem_group", "INDIVIDUAL", null), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall access policy checks passed");
process.exit(failed ? 1 : 0);
