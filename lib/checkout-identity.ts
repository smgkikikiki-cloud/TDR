/**
 * Whether an account's identity is settled well enough to start a NEW
 * charge, decided from facts already resolved -- never from a stored
 * flag and never from activation_source.
 *
 * This function does not take activation_source as an input at all. That
 * is deliberate, not an oversight: the bug this exists to close was a
 * bypass keyed on activation_source === 'LEGACY_PAID', and the only way
 * to make that bypass impossible to reintroduce by accident is for the
 * decision to have no field it could key on. A grandfathered account's
 * EXISTING billing relationship (Billing Portal, an existing
 * subscription) is a different question, answered elsewhere
 * (lib/billing.ts requireMember(), which never calls this at all) --
 * starting something NEW always asks this, of every account, the same
 * way, every time.
 */

export type IdentityFacts = {
  emailConfirmed: boolean;
  /** A TDR-owned OTP reservation reached CONFIRMED for the phone identity
   *  that is CURRENTLY this account's primary, non-revoked phone -- never
   *  merely that a verification once happened. */
  phoneVerified: boolean;
  postcode: string | null;
  isIndividual: boolean;
  companyName: string | null;
};

export type IdentityCheck = {
  ok: boolean;
  missing: string[];
};

export function evaluateCurrentVerifiedIdentity(facts: IdentityFacts): IdentityCheck {
  const missing: string[] = [];
  if (!facts.emailConfirmed) missing.push("confirm your email");
  if (!facts.phoneVerified) missing.push("verify your mobile phone");
  if (!facts.postcode) missing.push("add your postcode");
  if (!facts.isIndividual && !(facts.companyName || "").trim()) {
    missing.push("name your organization, or say you are an individual");
  }
  return { ok: missing.length === 0, missing };
}
