/**
 * Which canonical vehicle a registration row belongs to, one rule, used
 * everywhere a registration row is read.
 *
 * Precedence:
 *   1. registrations.canonical_model_id, when the row carries one --
 *      set directly by assignRegistrationIdentity for a car that may not
 *      have a legacy models row at all.
 *   2. the legacy bridge: registrations.model_id -> a canonical model
 *      whose current_vehicle_models.tdr_model_id crosswalks to it.
 *   3. unresolved.
 *
 * A row with model_id = NULL and canonical_model_id set is MAPPED. That
 * is the case this rule exists for: a car created in the admin today has
 * no legacy row until a release rebuilds the crosswalk, and before v41
 * such a row could never be told apart from a genuinely unmapped one.
 */

export type CanonicalPrecedenceInput = {
  canonicalModelId: string | null;
  legacyModelId: string | null;
};

export function resolveCanonicalModelId(
  input: CanonicalPrecedenceInput,
  reverseCrosswalk: (legacyModelId: string) => string | null,
): string | null {
  if (input.canonicalModelId) return input.canonicalModelId;
  if (input.legacyModelId) return reverseCrosswalk(input.legacyModelId) ?? null;
  return null;
}

/** A row is mapped when either half of the precedence resolves -- never
 *  `model_id is not null` alone, which is exactly the check that could
 *  never see a canonical-only row. */
export function isRegistrationMapped(input: CanonicalPrecedenceInput,
                                     reverseCrosswalk: (legacyModelId: string) => string | null): boolean {
  return resolveCanonicalModelId(input, reverseCrosswalk) !== null;
}
