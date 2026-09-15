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
  /**
   * At most one assertion per mechanism (a group with more than one from the
   * same mechanism never becomes a finding — see `AuditAnomaly`). Never
   * mutated.
   */
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

export type AuditAnomalyType = "duplicate_mechanism_assertions";

/**
 * Something the audit engine refuses to silently resolve. Today the only
 * anomaly type is more than one assertion from the *same* mechanism landing
 * under one comparability key — both mechanisms are expected to produce at
 * most one assertion per key (Mechanism A by construction in
 * `tdr_bridge/release.py`; Mechanism B by `canonical_object_map`'s
 * `unique (source_table, source_id, canonical_entity_type)` index), so this
 * should never happen live. If it ever does, the whole comparability group
 * is excluded from `findings` (never arbitrarily reduced to one row and
 * classified as if nothing were wrong) and reported here instead.
 */
export interface AuditAnomaly {
  type: AuditAnomalyType;
  comparabilityKey: string;
  mechanism: MechanismId;
  /** Every duplicate assertion for this mechanism in this group, deterministically ordered. Never mutated. */
  assertions: ExternalIdentityAssertion[];
}

export interface AuditSummary {
  totalFindings: number;
  totalAssertions: number;
  totalAnomalies: number;
  byClassification: Record<AuditClassification, number>;
  /** External identities whose assertions span more than one canonical entity type. */
  externalIdentitiesWithMultipleCanonicalEntityTypes: number;
}

export interface AuditReport {
  findings: AuditFinding[];
  anomalies: AuditAnomaly[];
  summary: AuditSummary;
}

function compareKeys(x: string, y: string): number {
  return x < y ? -1 : x > y ? 1 : 0;
}

/**
 * A total, deterministic order over assertions that does not depend on
 * insertion order — used both to order a finding's/anomaly's `assertions`
 * array and (for anomalies) to decide nothing about "which one wins," only
 * how to print them reproducibly.
 */
function compareAssertions(x: ExternalIdentityAssertion, y: ExternalIdentityAssertion): number {
  return (
    compareKeys(x.canonicalId ?? "", y.canonicalId ?? "")
    || compareKeys(x.mappingState, y.mappingState)
    || compareKeys(JSON.stringify(x.provenance), JSON.stringify(y.provenance))
  );
}

const MECHANISM_ORDER: Record<MechanismId, number> = {
  mechanism_a_release_crosswalk: 0,
  mechanism_b_canonical_object_map: 1,
};

const MECHANISM_IDS: readonly MechanismId[] = [
  "mechanism_a_release_crosswalk",
  "mechanism_b_canonical_object_map",
];

function groupByMechanism(assertions: ExternalIdentityAssertion[]): Map<MechanismId, ExternalIdentityAssertion[]> {
  const map = new Map<MechanismId, ExternalIdentityAssertion[]>();
  for (const assertion of assertions) {
    const list = map.get(assertion.provenance.mechanism);
    if (list) list.push(assertion);
    else map.set(assertion.provenance.mechanism, [assertion]);
  }
  return map;
}

function classify(
  a: ExternalIdentityAssertion | undefined,
  b: ExternalIdentityAssertion | undefined,
): AuditClassification {
  // Mechanism B's non-resolved states are reported for what they are,
  // whether or not Mechanism A also has an opinion — losing that signal by
  // folding it into a generic "derived_only" bucket would hide exactly the
  // information Phase 1A exists to surface (see EXTERNAL_IDENTITY_CONTRACT.md).
  // Classification is driven entirely by mappingState/trustLevel, never by
  // whether a non-resolved assertion happens to carry a contextual
  // canonicalId (see UnresolvedAssertion in types.ts).
  if (b?.mappingState === "ambiguous") return "mechanism_b_ambiguous";
  if (b?.mappingState === "retired") return "mechanism_b_retired";
  if (b?.mappingState === "unmatched") return "mechanism_b_unmatched";

  if (a && b && b.mappingState === "resolved" && b.trustLevel === "verified") {
    return a.canonicalId === b.canonicalId ? "exact_agreement" : "disagreement";
  }
  if (a && !b) return "derived_only";
  if (!a && b && b.mappingState === "resolved" && b.trustLevel === "verified") return "verified_only";

  // a is present, b is present but not resolved/ambiguous/retired/unmatched
  // (a mechanism-B mapping_state this contract does not yet know about) —
  // conservatively treat as "no verified counterpart" rather than guessing.
  return "derived_only";
}

/**
 * Classify a flat list of assertions. Deterministic: output ordering depends
 * only on assertion content (comparability key, then mechanism id), never on
 * input array order — shuffling the input yields identical `findings` and
 * `anomalies` order.
 *
 * A comparability group with more than one assertion from the same
 * mechanism is never classified as a normal finding — see `AuditAnomaly`.
 * No row is ever silently picked as "the" mechanism's answer.
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
  const anomalies: AuditAnomaly[] = [];

  for (const [key, groupAssertions] of groups) {
    const byMechanism = groupByMechanism(groupAssertions);

    const duplicateMechanisms = MECHANISM_IDS.filter((m) => (byMechanism.get(m)?.length ?? 0) > 1);
    if (duplicateMechanisms.length > 0) {
      for (const mechanism of duplicateMechanisms) {
        anomalies.push({
          type: "duplicate_mechanism_assertions",
          comparabilityKey: key,
          mechanism,
          assertions: [...(byMechanism.get(mechanism) ?? [])].sort(compareAssertions),
        });
      }
      // The whole group is excluded from normal findings: with more than one
      // assertion from one mechanism, there is no single "this mechanism's
      // answer" to classify against the other mechanism, and picking one
      // arbitrarily to produce a exact_agreement/disagreement verdict would
      // be exactly the silent selection this anomaly exists to prevent.
      continue;
    }

    const sample = groupAssertions[0];
    const a = byMechanism.get("mechanism_a_release_crosswalk")?.[0];
    const b = byMechanism.get("mechanism_b_canonical_object_map")?.[0];
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
  anomalies.sort(
    (x, y) => compareKeys(x.comparabilityKey, y.comparabilityKey) || compareKeys(x.mechanism, y.mechanism),
  );

  const byClassification = Object.fromEntries(
    AUDIT_CLASSIFICATIONS.map((c) => [c, 0]),
  ) as Record<AuditClassification, number>;
  for (const finding of findings) byClassification[finding.classification]++;

  const externalIdentitiesWithMultipleCanonicalEntityTypes = [...entityTypesByExternalId.values()].filter(
    (types) => types.size > 1,
  ).length;

  return {
    findings,
    anomalies,
    summary: {
      totalFindings: findings.length,
      totalAssertions: assertions.length,
      totalAnomalies: anomalies.length,
      byClassification,
      externalIdentitiesWithMultipleCanonicalEntityTypes,
    },
  };
}
