/**
 * Whether a NEW checkout can start, case by case -- the pure decision
 * (lib/checkout-identity.ts) that lib/access-policy-server.ts's
 * requireCurrentVerifiedIdentity() calls after resolving the facts from
 * Supabase. These are the exact four acceptance cases: LEGACY_PAID with a
 * gap in either direction must fail a NEW checkout while normal tools and
 * the Billing Portal (which never call this function at all) stay
 * reachable; a fully current LEGACY_PAID account, and an ordinary
 * verified account, both pass.
 */
import fs from "node:fs";
import { evaluateCurrentVerifiedIdentity } from "../lib/checkout-identity.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

console.log("1 — LEGACY_PAID, trusted phone exists, postcode missing");
{
  // activation_source is not a parameter of this function at all -- see
  // the case below that proves that structurally too. What LEGACY_PAID
  // actually grants (existing tools, existing billing) is unaffected by
  // this decision, because those paths never call it -- verified below.
  const r = evaluateCurrentVerifiedIdentity({
    emailConfirmed: true, phoneVerified: true,
    postcode: null, isIndividual: true, companyName: null,
  });
  check("NEW checkout is refused", r.ok, false);
  check("for the reason that is actually missing", r.missing, ["add your postcode"]);
}

console.log("\n2 — LEGACY_PAID, postcode exists, phone revoked");
{
  const r = evaluateCurrentVerifiedIdentity({
    emailConfirmed: true, phoneVerified: false,
    postcode: "10110", isIndividual: true, companyName: null,
  });
  check("NEW checkout is refused", r.ok, false);
  check("for the reason that is actually missing", r.missing, ["verify your mobile phone"]);
}

console.log("\n3 — LEGACY_PAID, current email + phone + complete profile");
{
  const r = evaluateCurrentVerifiedIdentity({
    emailConfirmed: true, phoneVerified: true,
    postcode: "10110", isIndividual: true, companyName: null,
  });
  check("NEW checkout is allowed", r.ok, true);
  check("nothing is missing", r.missing, []);
}

console.log("\n4 — an ordinary verified account (never grandfathered)");
{
  const r = evaluateCurrentVerifiedIdentity({
    emailConfirmed: true, phoneVerified: true,
    postcode: "10330", isIndividual: false, companyName: "TDR Co., Ltd.",
  });
  check("NEW checkout is allowed", r.ok, true);
}

console.log("\nthe structural guarantee that makes case 1/2 possible at all");
{
  const checkoutIdentity = fs.readFileSync("lib/checkout-identity.ts", "utf8");
  const identityFactsType = checkoutIdentity.slice(
    checkoutIdentity.indexOf("export type IdentityFacts"),
    checkoutIdentity.indexOf("export type IdentityCheck"));
  check("the IdentityFacts type has no activation-status field to key a bypass on",
    !/activation/i.test(identityFactsType));

  const policyServer = fs.readFileSync("lib/access-policy-server.ts", "utf8");
  const requireCurrentStart = policyServer.indexOf(
    "export async function requireCurrentVerifiedIdentity");
  const requireCurrentSrc = policyServer.slice(
    requireCurrentStart, policyServer.indexOf("\n}\n", requireCurrentStart));
  // The .select(...) column list and the ctx it builds from -- not the
  // explanatory comment above it, which is allowed to say the word.
  const selectAndBody = requireCurrentSrc.slice(requireCurrentSrc.indexOf(".select("));
  check("requireCurrentVerifiedIdentity no longer selects or reads activation_completed_at/activation_source",
    !/activation_(completed_at|source)/.test(selectAndBody));

  const requireMemberAccessSrc = policyServer.slice(
    policyServer.indexOf("export async function requireMemberAccess"),
    policyServer.indexOf("// Verified identity, for the few operations"));
  check("normal member tools (requireMemberAccess) never call the identity gate at all",
    !requireMemberAccessSrc.includes("evaluateCurrentVerifiedIdentity")
      && !requireMemberAccessSrc.includes("requireCurrentVerifiedIdentity("));

  const billing = fs.readFileSync("lib/billing.ts", "utf8");
  const billingPortalSrc = billing.slice(
    billing.indexOf("export async function createBillingPortal"),
    billing.indexOf("export async function createBillingPortal") + 600);
  check("the Billing Portal path calls plain requireMember, never the identity gate",
    billingPortalSrc.includes("requireMember(args.accessToken)")
      && !billingPortalSrc.includes("requireCurrentVerifiedIdentity"));
  check("NEW checkout is the only caller of the identity gate",
    (billing.match(/requireCurrentVerifiedIdentity\(/g) || []).length, 1);
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall checkout identity checks passed");
process.exit(failed ? 1 : 0);
