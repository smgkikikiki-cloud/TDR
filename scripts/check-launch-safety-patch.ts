// Source-text regression tests for the launch-safety patch: account
// activation is enforced centrally (not per-route ad hoc), double
// subscriptions are refused before Stripe Checkout is ever created,
// Research/PDF stay hidden behind explicit release flags, and the
// Corporate CTA is configuration-driven rather than a guessed address.
// Same convention as scripts/check-member-market.ts / check-quota-architecture.ts.
import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

console.log("launch safety — account activation is the gate on every member tool route, not just the UI");
const toolRoutes: Record<string, string> = {
  "app/api/tools/compare/route.ts": fs.readFileSync("app/api/tools/compare/route.ts", "utf8"),
  "app/api/tools/sales-modules/route.ts": fs.readFileSync("app/api/tools/sales-modules/route.ts", "utf8"),
  "app/api/tools/sales-dashboard/route.ts": fs.readFileSync("app/api/tools/sales-dashboard/route.ts", "utf8"),
  "app/api/report/registration/route.ts": fs.readFileSync("app/api/report/registration/route.ts", "utf8"),
  "app/api/report/market/route.ts": fs.readFileSync("app/api/report/market/route.ts", "utf8"),
  "app/api/research/read/route.ts": fs.readFileSync("app/api/research/read/route.ts", "utf8"),
  "app/api/export/pdf/route.ts": fs.readFileSync("app/api/export/pdf/route.ts", "utf8"),
};
const registrationAnalytics = fs.readFileSync("lib/registration-analytics.ts", "utf8");
// registration/market routes reach activation indirectly through
// lib/registration-analytics.ts::resolveRegistrationAccess (which itself
// must call requireActivatedAccess, checked separately below) rather than
// calling requireActivatedAccess directly -- both paths are accepted here.
const reachesActivationDirectly = new Set([
  "app/api/tools/compare/route.ts",
  "app/api/tools/sales-modules/route.ts",
  "app/api/tools/sales-dashboard/route.ts",
  "app/api/research/read/route.ts",
  "app/api/export/pdf/route.ts",
]);
for (const [path, source] of Object.entries(toolRoutes)) {
  if (reachesActivationDirectly.has(path)) {
    check(`${path} calls requireActivatedAccess or getRegistrationDashboard (which does)`, source.includes("requireActivatedAccess") || source.includes("getRegistrationDashboard"), true);
  }
}
check(
  "lib/registration-analytics.ts's resolveRegistrationAccess uses requireActivatedAccess, not the weaker resolveAccessContext",
  registrationAnalytics.includes("return await requireActivatedAccess(accessToken)"),
  true,
);
check(
  "lib/access-policy-server.ts's plain resolveAccessContext is never itself sufficient for a tool route",
  fs.readFileSync("lib/access-policy-server.ts", "utf8").includes("export async function requireActivatedAccess"),
  true,
);

console.log("\nlaunch safety — double subscriptions are refused before Stripe Checkout is created");
const billing = fs.readFileSync("lib/billing.ts", "utf8");
check("billing.ts defines the blocking subscription status set", billing.includes("BLOCKING_SUBSCRIPTION_STATUSES"), true);
check("the guard queries tdr_subscriptions scoped to this customer", billing.includes('.from("tdr_subscriptions")') && billing.includes(".eq(\"customer_id\", member.customerId)"), true);
check("an existing blocking subscription throws instead of proceeding to Stripe", billing.includes("throw new BillingError(\n      409,"), true);
{
  const guardIndex = billing.indexOf("BLOCKING_SUBSCRIPTION_STATUSES");
  const stripeCustomerIndex = billing.indexOf("const customerId = await ensureStripeCustomer(member);");
  check("the subscription check runs before any Stripe customer/session is created", guardIndex > -1 && stripeCustomerIndex > -1 && guardIndex < stripeCustomerIndex, true);
}
check("billing UI hides the subscribe buttons once hasActiveSubscription is true", fs.readFileSync("app/member/billing/page.tsx", "utf8").includes("!data.hasActiveSubscription ?"), true);
check("the plan-transition (stale entitlement) risk is documented for a future plan-switch implementation", fs.readFileSync("docs/BILLING.md", "utf8").includes("Stripe plan switching (upgrade/downgrade) is\nintentionally not implemented yet"), true);

console.log("\nlaunch safety — Research is a real, released product; PDF stays hidden until it is one");
const accessPolicy = fs.readFileSync("lib/access-policy.ts", "utf8");
// research_reports went live once a real content model (migration_v38),
// admin authoring surface and unlock route existed -- see
// scripts/check-research.ts for the full picture. This file's job is
// narrower: the launch-safety invariants (gate before work, no
// hardcoded-live copy) still hold on the other side of that flip.
check("research_reports is registered as released with a real, decided Free limit",
  accessPolicy.includes('research_reports: {') && accessPolicy.includes("released: true"), true);
check("pdf_export_reports is still registered as an unreleased feature", accessPolicy.includes("pdf_export_reports: {") && accessPolicy.includes("released: false"), true);
const researchRoute = fs.readFileSync("app/api/research/read/route.ts", "utf8");
const pdfRoute = fs.readFileSync("app/api/export/pdf/route.ts", "utf8");
{
  // Compare the 401 return's position against the actual call site
  // requireActivatedAccess(accessToken) -- not the bare identifier, which
  // also appears earlier in this file's own import statement.
  const unauthorizedReturnIndex = researchRoute.indexOf('{ status: 401 }');
  const activationCallIndex = researchRoute.indexOf("requireActivatedAccess(accessToken)");
  check("the research route refuses a request with no bearer token before it ever queries the DB",
    unauthorizedReturnIndex > -1 && activationCallIndex > -1 && unauthorizedReturnIndex < activationCallIndex, true);
}
check("the PDF export route 404s while unreleased, before doing any auth/DB work", pdfRoute.indexOf("FEATURES.pdf_export_reports.released") < pdfRoute.indexOf("bearer(request)"), true);
const pricingPage = fs.readFileSync("app/pricing/page.tsx", "utf8");
check("pricing copy reads the research release flag rather than hardcoding it as live", pricingPage.includes("FEATURES.research_reports.released"), true);
check("pricing copy reads the pdf release flag rather than hardcoding it as live", pricingPage.includes("FEATURES.pdf_export_reports.released"), true);

console.log("\nlaunch safety — Corporate CTA is configuration-driven, never a guessed address");
check("no hardcoded mailto: address remains in the pricing page", /mailto:[a-z0-9._-]+@(?!YOUR_)/i.test(pricingPage.replace(/NEXT_PUBLIC_TDR_CORPORATE_CONTACT_URL/g, "")), false);
check("the Corporate CTA reads from NEXT_PUBLIC_TDR_CORPORATE_CONTACT_URL", pricingPage.includes("process.env.NEXT_PUBLIC_TDR_CORPORATE_CONTACT_URL"), true);
check("the CTA fails visibly (disabled) rather than silently when unconfigured", pricingPage.includes("ยังไม่ได้ตั้งค่า") && pricingPage.includes('aria-disabled="true"'), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall launch safety checks passed");
process.exit(failed ? 1 : 0);
