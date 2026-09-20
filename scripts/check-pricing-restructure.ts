// Source-text + unit regression tests for the single-paid-tier pricing
// restructure: Individual (the ฿399/month middle tier) is scrapped, Pro
// is the only paid product, sold at three real commitment lengths
// (monthly/quarterly/annual -- not two separate tiers), a legacy
// tier_individual entitlement grandfathers into Pro rather than being
// silently dropped, and /pricing is finally reachable from the site's
// nav and footer. Same convention as check-access-policy.ts /
// check-launch-safety-patch.ts.
import fs from "node:fs";
import { resolveTierFromEntitlements, type EntitlementRow } from "../lib/access-policy.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

console.log("pricing restructure — Individual is gone, Pro is the only paid tier");
const accessPolicy = fs.readFileSync("lib/access-policy.ts", "utf8");
check('the Tier type is exactly "FREE" | "PRO"', accessPolicy.includes('export type Tier = "FREE" | "PRO";'), true);
check("TIER_PRODUCT no longer issues an Individual product", accessPolicy.includes('INDIVIDUAL: "tier_individual"'), false);
check(
  "a legacy tier_individual entitlement grandfathers into Pro rather than being silently dropped to Free",
  resolveTierFromEntitlements([{ product: "tier_individual", status: "ACTIVE", valid_until: null }] as EntitlementRow[]),
  "PRO",
);
check(
  "REVOKED tier_individual still grants nothing (grandfathering is not a blanket bypass)",
  resolveTierFromEntitlements([{ product: "tier_individual", status: "REVOKED", valid_until: null }] as EntitlementRow[]),
  "FREE",
);

console.log("\npricing restructure — Pro's three commitment lengths are real, decided numbers");
// lib/plans.ts imports the "@/" alias (TIER_PRODUCT), which only resolves
// under Next.js's bundler -- plain node can't import it directly, so this
// reads it as source text instead, same convention as the other
// cross-file checks below.
const plans = fs.readFileSync("lib/plans.ts", "utf8");
check("exactly three plans are defined, all planCode-prefixed pro_", (plans.match(/planCode:\s*"pro_/g) || []).length, 3);
check("covers exactly monthly/quarterly/annual, once each", (plans.match(/interval:\s*"(monthly|quarterly|annual)"/g) || []).map((m) => m.match(/"(\w+)"/)![1]).sort(), ["annual", "monthly", "quarterly"]);
check("monthly is ฿1,290, billed ฿1,290 per invoice", /interval:\s*"monthly",\s*priceThbPerMonth:\s*1290,\s*priceThbPerInterval:\s*1290,/.test(plans), true);
check("quarterly is ฿990/month, billed ฿2,970 upfront every 3 months", /interval:\s*"quarterly",\s*priceThbPerMonth:\s*990,\s*priceThbPerInterval:\s*990 \* 3,/.test(plans), true);
check("annual is ฿790/month, billed ฿9,480 upfront every year", /interval:\s*"annual",\s*priceThbPerMonth:\s*790,\s*priceThbPerInterval:\s*790 \* 12,/.test(plans), true);
check("every plan has its own distinct Stripe Price env var -- not a shared/guessed one", new Set(plans.match(/stripePriceEnvVar:\s*"STRIPE_PRICE_\w+"/g)).size, 3);
check("no Individual plan remains in the catalog", plans.includes('"individual_'), false);

console.log("\npricing restructure — the public pricing page reflects the real structure");
const pricingPage = fs.readFileSync("app/pricing/page.tsx", "utf8");
check("no Individual card remains", pricingPage.includes("Individual"), false);
check("the Pro card reads its prices from PLAN_CATALOG, not typed-in numbers", pricingPage.includes("PLAN_CATALOG") && pricingPage.includes("PRO_PLANS.map"), true);
check("Free's bullets read the real quota numbers, not stale copies", pricingPage.includes("FREE_POLICY.compareDailyLimit") && pricingPage.includes("FREE_POLICY.salesQueryDailyLimit"), true);
check('the Enterprise block is labeled "TDR Enterprise package", not "Team" or generic "Corporate"', pricingPage.includes("TDR Enterprise package"), true);
check("the Enterprise CTA is still the config-driven contact button (never a guessed address)", pricingPage.includes("NEXT_PUBLIC_TDR_CORPORATE_CONTACT_URL") && pricingPage.includes('aria-disabled="true"'), true);

console.log("\npricing restructure — billing UI offers all three intervals, not just monthly");
const billingPage = fs.readFileSync("app/member/billing/page.tsx", "utf8");
check('the plan list is no longer filtered to interval === "monthly" only', billingPage.includes('.filter((p) => p.interval === "monthly")'), false);
check("each plan button shows both the per-month rate and what actually gets billed per invoice", billingPage.includes("priceThbPerMonth") && billingPage.includes("priceThbPerInterval"), true);

console.log("\npricing restructure — /pricing is finally reachable from the site, not an orphan page");
const navigation = fs.readFileSync("lib/navigation.ts", "utf8");
const footer = fs.readFileSync("components/Footer.tsx", "utf8");
check("the primary nav (desktop + mobile drawer, single source of truth) links to /pricing", navigation.includes('{ href: "/pricing"'), true);
check("the footer links to /pricing", footer.includes('href="/pricing"'), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall pricing restructure checks passed");
process.exit(failed ? 1 : 0);
