/**
 * Phase 1A external-identity contract — pure types only.
 *
 * See docs/vehicle-platform/EXTERNAL_IDENTITY_CONTRACT.md for the full
 * vocabulary write-up. This file is the executable definition of that
 * vocabulary; keep the two in sync.
 *
 * This module has no side effects and no dependency on Supabase, Next.js, or
 * any I/O. It represents an *assertion* made by one existing mechanism about
 * how a legacy TDR identity relates to a canonical Vehicle Master identity —
 * never canonical truth by itself. Mechanism A (the release-build crosswalk)
 * and Mechanism B (`canonical_object_map`) both produce assertions in this
 * shape; nothing here changes what either mechanism does.
 */

/** Namespace an external identifier belongs to. Only one exists today. */
export type ExternalNamespace = "legacy_tdr";

/**
 * Normalized legacy source-entity kind. `canonical_object_map.source_table`
 * uses the raw Supabase table names (`brands`, `models`, `model_powertrains`,
 * `trims`); this contract normalizes those to singular nouns so a future
 * namespace is not forced to reuse TDR's own table-naming convention.
 */
export type ExternalEntityType = "brand" | "model" | "model_powertrain" | "trim";

/**
 * Canonical Vehicle Master entity kind. Matches
 * `canonical_object_map.canonical_entity_type`'s existing check constraint
 * exactly (`supabase/migration_v12_canonical_write_pipeline.sql`). "variant"
 * is deliberately not renamed to "Configuration" here — see
 * MASTER_ARCHITECTURE.md's "canonical identity graph" and INVARIANTS.md;
 * Phase 1A does not rename Variant in code or data.
 */
export type CanonicalEntityType = "brand" | "model" | "generation" | "variant" | "market_trim";

/**
 * The semantic state of a mapping attempt, independent of how much anyone
 * trusts it. `resolved` means "this mechanism landed on one specific
 * canonical entity" — it says nothing about whether that landing was derived
 * or verified; see `TrustLevel` for that axis.
 */
export type MappingState = "resolved" | "unmatched" | "ambiguous" | "retired";

/**
 * How much authority an assertion carries, independent of mapping state.
 * `derived` = produced by deterministic matching/aliasing/overrides, never
 * itself sufficient to unlock a write-sensitive operation. `verified` =
 * an explicit human/evidence action recorded the mapping as authoritative.
 * `none` = no assertion of identity was reached (unmatched/ambiguous/
 * retired all carry `none`).
 *
 * A `derived` assertion must never be silently promoted to `verified` by
 * this contract or by anything that consumes it — including agreeing with a
 * `verified` assertion elsewhere. See `auditAssertions` in audit.ts and its
 * "trust non-escalation" test.
 */
export type TrustLevel = "derived" | "verified" | "none";

/** Which existing mechanism produced a given assertion. */
export type MechanismId = "mechanism_a_release_crosswalk" | "mechanism_b_canonical_object_map";

/**
 * How an assertion came to exist. Kept as free-form/optional fields rather
 * than a closed enum because the two mechanisms record genuinely different
 * amounts of detail, and this contract must not invent provenance neither
 * mechanism's current data can prove (Mechanism A's exact match method —
 * override vs. explicit source marker vs. name/alias match — is not
 * persisted past `tdr_bridge/release.py` into the Supabase serving
 * projection, so it cannot be reconstructed from a live read).
 */
export interface Provenance {
  mechanism: MechanismId;
  /** Best-effort description of how the mapping was produced, where known. */
  matchBasis?: string | null;
  verifiedBy?: string | null;
  verifiedAt?: string | null;
  notes?: string | null;
}

/**
 * One mechanism's claim about how one external identity relates to one
 * canonical entity type. This is the atomic unit the audit engine compares.
 */
export interface ExternalIdentityAssertion {
  namespace: ExternalNamespace;
  externalEntityType: ExternalEntityType;
  externalId: string;
  canonicalEntityType: CanonicalEntityType;
  /** Null exactly when mappingState is not "resolved". */
  canonicalId: string | null;
  mappingState: MappingState;
  trustLevel: TrustLevel;
  provenance: Provenance;
}

/**
 * The comparability rule (task requirement §5): two assertions may only be
 * compared to each other when they agree on namespace, normalized external
 * entity type, external ID, AND canonical target entity type. Anything short
 * of that is a different question, not a disagreement. This key is exactly
 * that tuple, joined deterministically for grouping/sorting.
 */
export function comparabilityKey(
  a: Pick<ExternalIdentityAssertion, "namespace" | "externalEntityType" | "externalId" | "canonicalEntityType">,
): string {
  return `${a.namespace}::${a.externalEntityType}::${a.externalId}::${a.canonicalEntityType}`;
}

/** Groups assertions by external identity alone (namespace+entityType+id), ignoring canonical entity type. */
export function externalIdentityKey(
  a: Pick<ExternalIdentityAssertion, "namespace" | "externalEntityType" | "externalId">,
): string {
  return `${a.namespace}::${a.externalEntityType}::${a.externalId}`;
}
