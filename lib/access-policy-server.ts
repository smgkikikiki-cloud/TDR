// Server-side wiring for the access-policy module: token resolution, tier
// lookup, account-activation enforcement, and the atomic quota-consumption
// RPC call. Split from lib/access-policy.ts (which stays `@/`-import-free
// and unit-testable) because this file needs the Supabase admin client.
import { adminDb } from "@/lib/supabase";
import {
  getPolicy,
  periodKeyForMetric,
  resetsAtForMetric,
  resolveTierFromEntitlements,
  type EntitlementRow,
  type SalesModule,
  type Tier,
  type TierPolicy,
  type UsageMetric,
} from "@/lib/access-policy";
import { requestFingerprint } from "@/lib/request-fingerprint";

export class AccessPolicyError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface AccessContext {
  db: NonNullable<ReturnType<typeof adminDb>>;
  userId: string;
  email: string | null;
  emailConfirmed: boolean;
  tier: Tier;
  policy: TierPolicy;
}

// Auth + tier only -- does NOT require account activation. Used by routes
// a not-yet-activated account must still be able to reach (billing status,
// checkout, the profile/activation endpoints themselves). Any route that
// lets an account actually USE a member tool (Compare, Sales Tools,
// Research, PDF export) must use requireActivatedAccess() below instead.
export async function resolveAccessContext(accessToken: string): Promise<AccessContext> {
  const db = adminDb();
  if (!db) throw new AccessPolicyError(503, "access policy database is not configured");

  const { data: userData, error: userError } = await db.auth.getUser(accessToken);
  if (userError || !userData.user) {
    throw new AccessPolicyError(401, "invalid or expired member session");
  }

  const { data: entitlementRows, error: entitlementError } = await db
    .from("tdr_entitlements")
    .select("product,status,valid_until")
    .eq("user_id", userData.user.id);
  if (entitlementError) throw new AccessPolicyError(503, "could not resolve account tier");

  const tier = resolveTierFromEntitlements((entitlementRows ?? []) as EntitlementRow[]);
  return {
    db,
    userId: userData.user.id,
    email: userData.user.email ?? null,
    emailConfirmed: Boolean(userData.user.email_confirmed_at),
    tier,
    policy: getPolicy(tier),
  };
}

// --- Account activation -----------------------------------------------
//
// Free's business purpose is converting an anonymous visitor into a real,
// identifiable user -- a typed phone string in user_metadata is not
// verification and must never be treated as trusted identity. Activation
// requires: confirmed email (Supabase Auth), a verified phone identity
// (a real tdr_customer_phone_identities row -- OTP-confirmed by Supabase
// Auth, the same trusted table lib/billing.ts already relies on), a
// postcode, and either an organization name or explicit
// individual/not-affiliated status. `tdr_customer_profiles
// .activation_completed_at` is the single stored gate every tool route
// checks; evaluateAndPersistActivation() is the only place that computes
// and writes it.

export interface ActivationStatus {
  activated: boolean;
  emailConfirmed: boolean;
  phoneVerified: boolean;
  profileComplete: boolean;
  justActivated: boolean;
  activationSource: "VERIFIED" | "LEGACY_PAID" | null;
}

// "Phone verified" for activation purposes means a TDR-owned verification
// attempt (lib/phone-verification.ts) reached CONFIRMED status for the
// SAME phone that is this customer's current primary, non-revoked
// tdr_customer_phone_identities row -- not merely that such a row exists.
//
// Why: Supabase resolves phone-change OTP verification through
// auth.users.phone_change, which is not a unique column. Two different
// pending auth users can carry the same phone_change value, so in a
// theoretical collision Supabase's own verifyOtp could confirm a phone
// onto a DIFFERENT auth user than the one who requested the change. The
// tdr_sync_customer_from_auth trigger (migration_v21) would then still
// correctly attribute the confirmed phone to whichever auth user it
// actually landed on -- but that says nothing about which TDR *account*
// the SMS was meant to activate. Requiring a TDR-owned reservation,
// confirmed by re-reading the CALLER'S OWN current Auth state (never a
// client claim) and checked against the phone THAT SAME CALLER reserved,
// means activation can only ever be granted to the account that actually
// completed its own verification -- see lib/phone-verification.ts for the
// full reservation lifecycle.
async function hasTdrConfirmedPhoneVerification(db: AccessContext["db"], userId: string): Promise<boolean> {
  const { data: customer, error: customerError } = await db
    .from("tdr_customers").select("id").eq("auth_user_id", userId).maybeSingle();
  if (customerError) throw new AccessPolicyError(503, "could not resolve customer identity");
  if (!customer) return false;

  const { data: identity, error: identityError } = await db
    .from("tdr_customer_phone_identities")
    .select("phone_e164")
    .eq("customer_id", customer.id)
    .eq("is_primary", true)
    .is("revoked_at", null)
    .maybeSingle();
  if (identityError) throw new AccessPolicyError(503, "could not resolve verified phone status");
  if (!identity) return false;

  const { data: reservation, error: reservationError } = await db
    .from("tdr_phone_verification_attempts")
    .select("id")
    .eq("user_id", userId)
    .eq("phone_e164", identity.phone_e164)
    .eq("status", "CONFIRMED")
    .limit(1)
    .maybeSingle();
  if (reservationError) throw new AccessPolicyError(503, "could not resolve phone verification status");
  return Boolean(reservation);
}

// Recomputes activation from its constituent parts and persists
// activation_completed_at (and activation_source='VERIFIED') the first
// time every part is true. Safe to call repeatedly (idempotent past the
// first success) -- it never un-sets an already-granted activation, which
// is what preserves the migration_v34 legacy-paid grandfather
// (activation_source='LEGACY_PAID') set directly by the migration rather
// than computed here. Called by the profile save route and the
// phone-verification-confirm route -- never by a tool route, which should
// only ever READ the stored flag via requireActivatedAccess().
export async function evaluateAndPersistActivation(ctx: AccessContext): Promise<ActivationStatus> {
  const { data: profile, error: profileError } = await ctx.db
    .from("tdr_customer_profiles")
    .select("postcode,is_individual,company_name,activation_completed_at,activation_source")
    .eq("user_id", ctx.userId)
    .maybeSingle();
  if (profileError) throw new AccessPolicyError(503, "could not load profile for activation check");

  const phoneVerified = await hasTdrConfirmedPhoneVerification(ctx.db, ctx.userId);
  const profileComplete = Boolean(
    profile?.postcode && (profile.is_individual || (profile.company_name && profile.company_name.trim())),
  );
  const activated = ctx.emailConfirmed && phoneVerified && profileComplete;
  const wasAlreadyActivated = Boolean(profile?.activation_completed_at);

  if (activated && !wasAlreadyActivated) {
    const { error } = await ctx.db.from("tdr_customer_profiles")
      .update({ activation_completed_at: new Date().toISOString(), activation_source: "VERIFIED", updated_at: new Date().toISOString() })
      .eq("user_id", ctx.userId);
    if (error) throw new AccessPolicyError(503, "could not record account activation");
  }

  return {
    activated: activated || wasAlreadyActivated,
    emailConfirmed: ctx.emailConfirmed,
    phoneVerified,
    profileComplete,
    justActivated: activated && !wasAlreadyActivated,
    activationSource: (wasAlreadyActivated ? profile?.activation_source : activated ? "VERIFIED" : null) ?? null,
  };
}

/** What an ordinary member tool asks for: a real session, and the tier and
 *  quota that come with it.
 *
 *  Signing in is the entitlement. A member who cannot receive an OTP still
 *  paid for Pro, or still counts as the Free reader the tier was written
 *  for, and holding the product shut until they complete a profile
 *  withholds what they already have rather than protecting anything.
 *  Phone, postcode and company are enrichment, collected at /member/profile
 *  because they are useful, never because a dashboard depends on them.
 *
 *  requireActivatedAccess below still exists for the operations where
 *  identity is the point -- paying is one -- and nothing else should reach
 *  for it. */
export async function requireMemberAccess(accessToken: string): Promise<AccessContext> {
  return resolveAccessContext(accessToken);
}

// Verified identity, for the few operations that genuinely turn on who the
// member is rather than what they are entitled to. Checkout is the case:
// money moves, so a confirmed email, an OTP-verified phone and a complete
// billing profile are the operation's own requirements. Product routes use
// requireMemberAccess() instead -- see the note there.
export async function requireActivatedAccess(accessToken: string): Promise<AccessContext> {
  const ctx = await resolveAccessContext(accessToken);
  const { data: profile, error } = await ctx.db
    .from("tdr_customer_profiles")
    .select("activation_completed_at")
    .eq("user_id", ctx.userId)
    .maybeSingle();
  if (error) throw new AccessPolicyError(503, "could not verify account activation");
  if (!profile?.activation_completed_at) {
    throw new AccessPolicyError(
      403,
      "account activation required: confirm your email, verify your mobile phone, and complete your profile at /member/profile",
    );
  }
  return ctx;
}

export interface QuotaResult {
  allowed: boolean;
  used: number;
  limit: number | null;
  remaining: number | null;
  resets_at: string;
}

// Consumes one unit of `metric` quota for `userId`, atomically, via the
// tdr_consume_usage() RPC (migration_v34). `fingerprintParts` must be the
// full set of semantic parameters that make this request the request it
// is (dimension, window, filters, trim ids, ...) -- see
// requestFingerprint() above for why. One top-level route should call
// this exactly once per logical action; internal helper functions it
// calls must never call this themselves.
export async function consumeUsage(
  ctx: Pick<AccessContext, "db" | "userId">,
  metric: UsageMetric,
  limit: number | null,
  fingerprintParts: Array<string | number | boolean | null | undefined>,
): Promise<QuotaResult> {
  const now = new Date();
  const periodKey = periodKeyForMetric(metric, now);
  const fingerprint = requestFingerprint(ctx.userId, metric, fingerprintParts);
  const { data, error } = await ctx.db.rpc("tdr_consume_usage", {
    p_user_id: ctx.userId,
    p_metric: metric,
    p_period_key: periodKey,
    p_limit: limit,
    p_action_id: fingerprint,
  });
  if (error) throw new AccessPolicyError(503, `could not verify ${metric} quota`);
  const row = Array.isArray(data) ? data[0] : data;
  const used = Number(row?.used ?? 0);
  return {
    allowed: Boolean(row?.allowed),
    used,
    limit,
    remaining: limit === null ? null : Math.max(limit - used, 0),
    resets_at: resetsAtForMetric(metric, now),
  };
}

export async function requireUsage(
  ctx: Pick<AccessContext, "db" | "userId">,
  metric: UsageMetric,
  limit: number | null,
  fingerprintParts: Array<string | number | boolean | null | undefined>,
): Promise<QuotaResult> {
  const result = await consumeUsage(ctx, metric, limit, fingerprintParts);
  if (!result.allowed) {
    throw new AccessPolicyError(429, `${metric} quota exceeded for this period`);
  }
  return result;
}

export async function getSalesModuleSelection(
  db: AccessContext["db"],
  userId: string,
  cycleKey: string,
): Promise<SalesModule[] | null> {
  const { data, error } = await db
    .from("tdr_sales_module_selection")
    .select("modules")
    .eq("user_id", userId)
    .eq("cycle_key", cycleKey)
    .maybeSingle();
  if (error) throw new AccessPolicyError(503, "could not load sales module selection");
  return (data?.modules as SalesModule[] | undefined) ?? null;
}

export async function setSalesModuleSelection(
  db: AccessContext["db"],
  userId: string,
  cycleKey: string,
  modules: SalesModule[],
): Promise<void> {
  const existing = await getSalesModuleSelection(db, userId, cycleKey);
  if (existing) {
    const same = existing.length === modules.length && existing.every((m) => modules.includes(m));
    if (!same) {
      throw new AccessPolicyError(409, "sales module selection is locked for this cycle");
    }
    return;
  }
  const { error } = await db.from("tdr_sales_module_selection").insert({
    user_id: userId,
    cycle_key: cycleKey,
    modules,
  });
  if (error) throw new AccessPolicyError(503, "could not save sales module selection");
}
