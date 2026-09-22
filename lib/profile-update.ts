/**
 * What one profile save changes, decided before anything is written.
 *
 * The profile is enrichment, edited a field at a time, so the rule is
 * about absence: a body that omits a key must leave that key exactly as
 * it was. A member fixing their postcode is not also saying they withdrew
 * marketing consent and are no longer a company. Presence is what counts
 * -- an explicit false or an empty string is an edit and still writes;
 * omitting the key is not an edit at all.
 *
 * "Complete" is computed from the row the save produces, not from the
 * fact that a save happened: a postcode, and either an organization name
 * or an explicit statement of being an individual.
 */

export type ProfileRow = {
  postcode?: string | null;
  is_individual?: boolean | null;
  company_name?: string | null;
  profile_completed_at?: string | null;
};

export type ProfilePlan = {
  /** Columns to write. Empty when the request asked for no change. */
  changes: Record<string, unknown>;
  touched: boolean;
  isIndividual: boolean;
  profileComplete: boolean;
  justCompleted: boolean;
  /** A validation message, when the request cannot be applied at all. */
  error: string | null;
};

export const MARKETING_FIELDS = ["marketing_consent"] as const;

export function planProfileUpdate(
  body: Record<string, unknown>,
  existing: ProfileRow | null,
  now: string,
  consentVersion: string,
): ProfilePlan {
  const sent = (key: string) => Object.prototype.hasOwnProperty.call(body, key);
  const changes: Record<string, unknown> = {};

  if (sent("postcode")) {
    const postcode = typeof body.postcode === "string" ? body.postcode.trim() : "";
    if (postcode && !/^[0-9]{4,10}$/.test(postcode)) {
      return {
        changes: {}, touched: false, isIndividual: existing?.is_individual !== false,
        profileComplete: false, justCompleted: false,
        error: "postcode must be 4-10 digits",
      };
    }
    changes.postcode = postcode || null;
  }

  if (sent("is_individual")) changes.is_individual = body.is_individual !== false;
  // Whether this is a company account is read from the request when it
  // says so, and from the stored row when it does not.
  const isIndividual = sent("is_individual")
    ? body.is_individual !== false
    : existing?.is_individual !== false;
  // A company name belongs to a company account. Two things can touch it:
  // the request naming it directly, or the account switching TO individual
  // -- which clears it, because a company name has no home on an
  // individual account. Switching (or staying) a company account with no
  // company_name in the request is not an edit to the name at all: the
  // stored value survives untouched. This is the exact distinction the
  // earlier `sent("company_name") || sent("is_individual")` check
  // collapsed -- it cleared company_name any time is_individual was sent,
  // even `is_individual: false` with no company_name in the body.
  if (sent("company_name")) {
    const companyName = typeof body.company_name === "string" ? body.company_name.trim() : "";
    changes.company_name = isIndividual ? null : (companyName || null);
  } else if (sent("is_individual") && isIndividual && existing?.company_name) {
    // Only when THIS request is the one declaring individual status --
    // never as a side effect of some other field being edited on an
    // account that happens to already be (or default to) individual.
    changes.company_name = null;
  }

  if (sent("marketing_consent")) {
    const consented = body.marketing_consent === true;
    changes.marketing_consent = consented;
    if (consented) {
      changes.marketing_consent_at = now;
      changes.marketing_consent_version = consentVersion;
    }
  }

  const postcode = "postcode" in changes ? changes.postcode : existing?.postcode ?? null;
  const companyName = "company_name" in changes
    ? changes.company_name : existing?.company_name ?? null;
  const profileComplete = Boolean(
    postcode && (isIndividual || String(companyName || "").trim()));
  const justCompleted = profileComplete && !existing?.profile_completed_at;
  if (justCompleted) changes.profile_completed_at = now;

  return {
    changes,
    touched: Object.keys(changes).length > 0,
    isIndividual,
    profileComplete,
    justCompleted,
    error: null,
  };
}
