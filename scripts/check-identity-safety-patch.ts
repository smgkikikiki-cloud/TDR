// Regression coverage for the identity-safety patch: TDR-owned phone
// verification reservations (closing the Supabase phone_change ambiguity
// gap), honest legacy-compatibility provenance, and a trusted-identity-
// only Checkout path. Structural checks follow this repo's established
// check-*.ts convention (see check-quota-architecture.ts /
// check-launch-safety-patch.ts) since lib/phone-verification.ts and
// lib/billing.ts both need the Supabase admin client and so can't be
// unit-tested via the plain-Node `@/`-alias-free convention; the market
// fingerprint completeness check IS a real behavioral unit test, since
// requestFingerprint is pure and alias-free.
import fs from "node:fs";
import { requestFingerprint } from "../lib/request-fingerprint.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const phoneVerification = fs.readFileSync("lib/phone-verification.ts", "utf8");
const accessPolicyServer = fs.readFileSync("lib/access-policy-server.ts", "utf8");
const billing = fs.readFileSync("lib/billing.ts", "utf8");
const migration = fs.readFileSync("supabase/migration_v34_access_policy_and_quotas.sql", "utf8").toLowerCase();

function functionBody(source: string, signature: string): string {
  const start = source.indexOf(signature);
  if (start === -1) throw new Error(`signature not found: ${signature}`);

  // A parameter type (e.g. `args: { accessToken: string; ... }`) or an
  // inline return-type object (e.g. `Promise<Foo & { phone: string }>`)
  // can itself contain a "{ ... }" before the real function body opens.
  // Find the parameter list's own matching close-paren first (tracking
  // "(" / ")" depth only, ignoring braces entirely, so embedded object
  // types in the parameter list never confuse this step), then take the
  // LAST "{" on that same signature line (everything up to the next
  // newline) as the body opener: any inline object type on that line is
  // self-contained (opened and closed within the line), so the final "{"
  // on the line is always the one that actually opens the function body.
  const parenStart = source.indexOf("(", start);
  let parenDepth = 0;
  let paramListEnd = -1;
  for (let i = parenStart; i < source.length; i++) {
    if (source[i] === "(") parenDepth++;
    if (source[i] === ")") {
      parenDepth--;
      if (parenDepth === 0) { paramListEnd = i; break; }
    }
  }
  if (paramListEnd === -1) throw new Error(`unbalanced parameter list for: ${signature}`);

  const nextNewline = source.indexOf("\n", paramListEnd);
  const signatureLineTail = source.slice(paramListEnd, nextNewline === -1 ? source.length : nextNewline);
  const lastBraceOffset = signatureLineTail.lastIndexOf("{");
  if (lastBraceOffset === -1) throw new Error(`no function body opening brace found on the signature line for: ${signature}`);
  const braceStart = paramListEnd + lastBraceOffset;

  let depth = 0;
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}") { depth--; if (depth === 0) return source.slice(braceStart, i + 1); }
  }
  throw new Error(`unbalanced braces for: ${signature}`);
}

console.log("identity safety — a Supabase phone identity alone never activates an account");
const activationCheckFn = functionBody(accessPolicyServer, "async function hasTdrConfirmedPhoneVerification(");
check(
  "activation reads tdr_customer_phone_identities (the identity)",
  activationCheckFn.includes('.from("tdr_customer_phone_identities")'),
  true,
);
check(
  "activation ALSO requires a matching CONFIRMED tdr_phone_verification_attempts row, not identity existence alone",
  activationCheckFn.includes('.from("tdr_phone_verification_attempts")')
    && activationCheckFn.includes('.eq("status", "CONFIRMED")'),
  true,
);
check(
  "the reservation lookup is scoped to this exact user_id (reservation for user A cannot activate user B)",
  activationCheckFn.includes('.eq("user_id", userId)'),
  true,
);
check(
  "the reservation lookup requires the phone to equal the customer's CURRENT verified identity phone (a confirmed-but-different phone cannot activate)",
  activationCheckFn.includes('.eq("phone_e164", identity.phone_e164)'),
  true,
);
check(
  "identity presence alone (no matching reservation) returns false, not true",
  activationCheckFn.includes("if (!identity) return false;"),
  true,
);

console.log("\nidentity safety — TDR-owned reservation lifecycle");
const reserveFn = functionBody(phoneVerification, "export async function reservePhoneVerification(");
check(
  "reserving rejects a phone already verified for a DIFFERENT customer",
  reserveFn.includes("existingIdentity.customer_id !== customerId"),
  true,
);
check(
  "reserving cancels this user's own prior PENDING attempt first (one active reservation per user)",
  reserveFn.includes('.eq("status", "PENDING")') && reserveFn.includes('status: "CANCELLED"'),
  true,
);
check(
  "a unique-violation on insert (another active reservation for this phone) is surfaced as a 409, not a 500",
  reserveFn.includes('"23505"') && reserveFn.includes("409"),
  true,
);
check(
  "reserving runs lazy cleanup of stale attempts before checking phone availability",
  reserveFn.includes("tdr_expire_stale_phone_verification_attempts"),
  true,
);

const confirmFn = functionBody(phoneVerification, "export async function confirmPhoneVerification(");
check(
  "confirmation is scoped to a PENDING reservation for THIS caller's own user id",
  confirmFn.includes('.eq("user_id", user.id)') && confirmFn.includes('.eq("status", "PENDING")'),
  true,
);
check(
  "an expired reservation is marked EXPIRED and rejected, not silently confirmed",
  confirmFn.includes("new Date(reservation.expires_at).getTime() <= Date.now()") && confirmFn.includes('"EXPIRED"'),
  true,
);
check(
  "confirmation requires the Auth-confirmed phone to EXACTLY equal the reserved phone",
  confirmFn.includes("currentPhone !== reservation.phone_e164"),
  true,
);
check(
  "confirmation requires phone_confirmed_at to be set (not merely present on the user object)",
  confirmFn.includes("currentPhoneConfirmed"),
  true,
);
check(
  "confirmation re-reads the caller's OWN current Auth user via their OWN access token, never trusting a client claim",
  confirmFn.includes("requireUser(db, accessToken)") || phoneVerification.includes("db.auth.getUser(accessToken)"),
  true,
);

console.log("\nidentity safety — legacy compatibility never fakes OTP provenance");
check("migration_v34 does not insert into tdr_customer_phone_identities anywhere", migration.includes("insert into public.tdr_customer_phone_identities"), false);
check("legacy grandfather is tagged activation_source = LEGACY_PAID, not VERIFIED", migration.includes("activation_source = coalesce(p.activation_source, 'legacy_paid')"), true);
check(
  "evaluateAndPersistActivation only ever writes activation_source = VERIFIED for a freshly-computed activation",
  functionBody(accessPolicyServer, "export async function evaluateAndPersistActivation(").includes('activation_source: "VERIFIED"'),
  true,
);

console.log("\nidentity safety — Checkout requires a fully activated, trusted-phone identity");
check("billing.ts never reads a user_metadata property anywhere in code (mentions in comments explaining its removal are fine)", billing.includes(".user_metadata"), false);
const createCheckoutFn = functionBody(billing, "export async function createCheckout(");
check("createCheckout resolves the member via requireCheckoutEligibleMember (not the phone-optional requireMember)", createCheckoutFn.includes("requireCheckoutEligibleMember("), true);
const eligibleMemberFn = functionBody(billing, "export async function requireCheckoutEligibleMember(");
check("requireCheckoutEligibleMember recomputes verified identity rather than trusting a stored flag", eligibleMemberFn.includes("requireCurrentVerifiedIdentity("), true);
check("requireCheckoutEligibleMember refuses to proceed without a trusted phone on file", eligibleMemberFn.includes("if (!member.phone)"), true);
const requireMemberFn = functionBody(billing, "export async function requireMember(");
check("requireMember resolves phone ONLY from the trusted tdr_customer_phone_identities ledger", requireMemberFn.includes('.from("tdr_customer_phone_identities")'), true);
check("requireMember never requires a phone to succeed (billing status/profile lookup stays reachable)", /if \(!phone\)/.test(requireMemberFn), false);

console.log("\nidentity safety — existing legacy paid customer keeps Billing Portal/status access");
const portalFn = functionBody(billing, "export async function createBillingPortal(");
const statusFn = functionBody(billing, "export async function getBillingStatus(");
check("createBillingPortal uses the phone-optional requireMember, not requireCheckoutEligibleMember", portalFn.includes("requireMember(") && !portalFn.includes("requireCheckoutEligibleMember("), true);
check("getBillingStatus uses the phone-optional requireMember, not requireCheckoutEligibleMember", statusFn.includes("requireMember(") && !statusFn.includes("requireCheckoutEligibleMember("), true);

console.log("\nidentity safety — market quota fingerprint now covers every output-changing parameter");
const marketRoute = fs.readFileSync("app/api/report/market/route.ts", "utf8");
check("the market fingerprint includes limit", /consumeMarketReportQuota\(ctx, \[[\s\S]{0,300}?\blimit,/.test(marketRoute), true);
check("the market fingerprint includes trendMonths", /consumeMarketReportQuota\(ctx, \[[\s\S]{0,300}?trendMonths,/.test(marketRoute), true);
check("filter fingerprinting is canonicalized (sorted) so query-param ordering can't cause a spurious fresh charge", marketRoute.includes("canonicalFilterFingerprint"), true);

console.log("\nidentity safety — requestFingerprint behaviorally differs on limit/trendMonths (real unit test, not just structural)");
const T0 = 1_800_000_000_000;
check(
  "different `limit` produces a different fingerprint for otherwise-identical parts",
  requestFingerprint("user-1", "sales_query", ["model", "month", "2026-06-01", "2026-06-30", "", "", false, 100, 6, "{}"], 5000, T0)
    === requestFingerprint("user-1", "sales_query", ["model", "month", "2026-06-01", "2026-06-30", "", "", false, 250, 6, "{}"], 5000, T0),
  false,
);
check(
  "different `trendMonths` produces a different fingerprint for otherwise-identical parts",
  requestFingerprint("user-1", "sales_query", ["model", "month", "2026-06-01", "2026-06-30", "", "", false, 100, 6, "{}"], 5000, T0)
    === requestFingerprint("user-1", "sales_query", ["model", "month", "2026-06-01", "2026-06-30", "", "", false, 100, 3, "{}"], 5000, T0),
  false,
);
check(
  "identical parts (including limit/trendMonths) in the same coalesce window still coalesce",
  requestFingerprint("user-1", "sales_query", ["model", "month", "2026-06-01", "2026-06-30", "", "", false, 100, 6, "{}"], 5000, T0)
    === requestFingerprint("user-1", "sales_query", ["model", "month", "2026-06-01", "2026-06-30", "", "", false, 100, 6, "{}"], 5000, T0 + 500),
  true,
);

console.log(failed ? `\n${failed} check(s) failed` : "\nall identity safety checks passed");
process.exit(failed ? 1 : 0);
