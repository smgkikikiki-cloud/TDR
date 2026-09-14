/**
 * Phase 1A read-only audit engine — pure logic, no I/O.
 *
 * Takes a flat list of ExternalIdentityAssertion values (produced by either
 * mechanism's adapter, see mechanism-adapters.ts) and classifies them per
 * comparability group. This module never mutates an assertion, never
 * chooses a "winning" mechanism, and never upgrades a derived assertion's
 * trust level. It answers exactly one question per group: "what does each
 * mechanism currently assert here, and how do those assertions relate?" —
 * not "which one is right."
 *
 * See docs/vehicle-platform/EXTERNAL_IDENTITY_CONTRACT.md "Audit
 * classifications" for the human-readable description of each outcome below.
 */
import {
  type CanonicalEntityType,
  type ExternalIdentityAssertion,
  type MechanismId,
  comparabilityKey,
  externalIdentityKey,
} from "./types.ts";

export type AuditClassification =
  | "exact_agreement"
  | "disagreement"
  | "derived_only"
  | "verified_only"
  | "mechanism_b_unmatched"
  | "mechanism_b_ambiguous"
  | "mechanism_b_retired";

/** Fixed, documented ordering — also the key order in AuditSummary.byClassification. */
export const AUDIT_CLASSIFICATIONS: readonly AuditClassification[] = [
  "exact_agreement",
  "disagreement",
  "derived_only",
  "verified_only",
  "mechanism_b_unmatched",
  "mechanism_b_ambiguous",
  "mechanism_b_retired",
];

export interface AuditFinding {
  comparabilityKey: string;
  namespace: ExternalIdentityAssertion["namespace"];
  externalEntityType: ExternalIdentityAssertion["externalEntityType"];
  externalId: string;
  canonicalEntityType: CanonicalEntityType;
  classification: AuditClassification;
  /** Every assertion found in this comparability group, sorted by mechanism id. Never mutated. */
  assertions: ExternalIdentityAssertion[];
  /**
   * Other canonical entity types asserted (by either mechanism) for this
   * same external identity, outside this group. Non-empty here means "this
   * external ID has assertions at another canonical scope too" — those are
   * their own separate findings (see task requirement §5), surfaced here
   * only for visibility, never merged into this finding's classification.
   */
  otherCanonicalEntityTypesForSameExternalId: CanonicalEntityType[];
}

export interface AuditSummary {
  totalFindings: number;
  totalAssertions: number;
  byClassification: Record<AuditClassification, number>;
  /** External identities whose assertions span more than one canonical entity type. */
  externalIdentitiesWithMultipleCanonicalEntityTypes: number;
}

export interface AuditReport {
  findings: AuditFinding[];
  summary: AuditSummary;
}

function byMechanism(
  assertions: ExternalIdentityAssertion[],
  mechanism: MechanismId,
): ExternalIdentityAssertion | undefined {
  // Both mechanisms are constrained (Mechanism A by construction in
  // tdr_bridge/release.py; Mechanism B by canonical_object_map's unique
  // (source_table, source_id, canonical_entity_type) index) to produce at
  // most one assertion per comparability key. If that is ever violated —
  // a data anomaly, not an expected state — take the first in sorted order
  // rather than throwing, so a read-only audit never crashes on bad data.
  return assertions
    .filter((a) => a.provenance.mechanism === mechanism)
    .sort((a, b) => compareKeys(a.canonicalId ?? "", b.canonicalId ?? ""))[0];
}

function classify(
  a: ExternalIdentityAssertion | undefined,
  b: ExternalIdentityAssertion | undefined,
): AuditClassification {
  // Mechanism B's non-resolved states are reported for what they are,
  // whether or not Mechanism A also has an opinion — losing that signal by
  // folding it into a generic "derived_only" bucket would hide exactly the
  // information Phase 1A exists to surface (see EXTERNAL_IDENTITY_CONTRACT.md).
  if (b?.mappingState === "ambiguous") return "mechanism_b_ambiguous";
  if (b?.mappingState === "retired") return "mechanism_b_retired";
  if (b?.mappingState === "unmatched") return "mechanism_b_unmatched";

  if (a && b && b.trustLevel === "verified") {
    return a.canonicalId === b.canonicalId ? "exact_agreement" : "disagreement";
  }
  if (a && !b) return "derived_only";
  if (!a && b && b.trustLevel === "verified") return "verified_only";

  // a is present, b is present but neither verified/unmatched/ambiguous/
  // retired (a mechanism-B mapping_state this contract does not yet know
  // about) — conservatively treat as "no verified counterpart" rather than
  // guessing at agreement.
  return "derived_only";
}

const MECHANISM_ORDER: Record<MechanismId, number> = {
  mechanism_a_release_crosswalk: 0,
  mechanism_b_canonical_object_map: 1,
};

function compareKeys(x: string, y: string): number {
  return x < y ? -1 : x > y ? 1 : 0;
}

/**
 * Classify a flat list of assertions. Deterministic: output ordering depends
 * only on assertion content (comparability key, then mechanism id), never on
 * input array order — shuffling the input yields identical `findings` order.
 */
export function auditAssertions(assertions: ExternalIdentityAssertion[]): AuditReport {
  const groups = new Map<string, ExternalIdentityAssertion[]>();
  const entityTypesByExternalId = new Map<string, Set<CanonicalEntityType>>();

  for (const assertion of assertions) {
    const key = comparabilityKey(assertion);
    const group = groups.get(key);
    if (group) group.push(assertion);
    else groups.set(key, [assertion]);

    const idKey = externalIdentityKey(assertion);
    const types = entityTypesByExternalId.get(idKey);
    if (types) types.add(assertion.canonicalEntityType);
    else entityTypesByExternalId.set(idKey, new Set([assertion.canonicalEntityType]));
  }

  const findings: AuditFinding[] = [];
  for (const [key, groupAssertions] of groups) {
    const sample = groupAssertions[0];
    const a = byMechanism(groupAssertions, "mechanism_a_release_crosswalk");
    const b = byMechanism(groupAssertions, "mechanism_b_canonical_object_map");
    const idKey = externalIdentityKey(sample);
    const allTypesForId = entityTypesByExternalId.get(idKey) ?? new Set<CanonicalEntityType>();
    const otherTypes = [...allTypesForId]
      .filter((t) => t !== sample.canonicalEntityType)
      .sort(compareKeys);

    findings.push({
      comparabilityKey: key,
      namespace: sample.namespace,
      externalEntityType: sample.externalEntityType,
      externalId: sample.externalId,
      canonicalEntityType: sample.canonicalEntityType,
      classification: classify(a, b),
      assertions: [...groupAssertions].sort(
        (x, y) => MECHANISM_ORDER[x.provenance.mechanism] - MECHANISM_ORDER[y.provenance.mechanism],
      ),
      otherCanonicalEntityTypesForSameExternalId: otherTypes,
    });
  }

  findings.sort((x, y) => compareKeys(x.comparabilityKey, y.comparabilityKey));

  const byClassification = Object.fromEntries(
    AUDIT_CLASSIFICATIONS.map((c) => [c, 0]),
  ) as Record<AuditClassification, number>;
  for (const finding of findings) byClassification[finding.classification]++;

  const externalIdentitiesWithMultipleCanonicalEntityTypes = [...entityTypesByExternalId.values()].filter(
    (types) => types.size > 1,
  ).length;

  return {
    findings,
    summary: {
      totalFindings: findings.length,
      totalAssertions: assertions.length,
      byClassification,
      externalIdentitiesWithMultipleCanonicalEntityTypes,
    },
  };
}
