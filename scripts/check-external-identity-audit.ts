import {
  auditAssertions,
  type AuditClassification,
} from "../lib/external-identity/audit.ts";
import {
  InvalidMechanismBRowError,
  assertionFromMechanismBRow,
  assertionsFromMechanismABrands,
  assertionsFromMechanismAModels,
  assertionsFromMechanismBRows,
  SOURCE_TABLE_TO_EXTERNAL_ENTITY_TYPE,
  type MechanismBRow,
} from "../lib/external-identity/mechanism-adapters.ts";
import { comparabilityKey, type ExternalIdentityAssertion } from "../lib/external-identity/types.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else {
    console.log(`  ok   ${name}`);
  }
}
function ok(name: string, condition: boolean) {
  if (!condition) { failed++; console.log(`  FAIL ${name}`); }
  else console.log(`  ok   ${name}`);
}

function findingFor(report: ReturnType<typeof auditAssertions>, key: string) {
  return report.findings.find((f) => f.comparabilityKey === key);
}

function classificationCounts(report: ReturnType<typeof auditAssertions>) {
  const nonZero: Partial<Record<AuditClassification, number>> = {};
  for (const [k, v] of Object.entries(report.summary.byClassification)) {
    if (v > 0) nonZero[k as AuditClassification] = v;
  }
  return nonZero;
}

// ---------------------------------------------------------------------------
// Mechanism adapters — source_table normalization, and the corrected
// canonicalId / mappingState invariant:
//   mappingState === "resolved"  => canonicalId non-null, trust derived|verified
//   mappingState !== "resolved"  => trust "none", canonicalId may be null OR a
//                                    retained contextual value that must never
//                                    imply a resolution.
// ---------------------------------------------------------------------------

console.log("mechanism adapters — normalization and the corrected mapping-state invariant");

check(
  "source_table normalizes to singular external entity types",
  SOURCE_TABLE_TO_EXTERNAL_ENTITY_TYPE,
  { brands: "brand", models: "model", model_powertrains: "model_powertrain", trims: "trim" },
);

const skippedNullBrand = assertionsFromMechanismABrands([
  { canonical_id: "toyota", tdr_brand_id: null },
  { canonical_id: "honda", tdr_brand_id: "brand-uuid-1" },
]);
check("mechanism A skips rows with no tdr id instead of asserting unmatched", skippedNullBrand.length, 1);
ok("mechanism A never emits mappingState other than resolved", skippedNullBrand.every((a) => a.mappingState === "resolved"));
ok("mechanism A assertions are always trustLevel derived", skippedNullBrand.every((a) => a.trustLevel === "derived"));

{
  // Unmatched never becomes resolved solely because a canonical ID happens
  // to be present — the type allows canonicalId on an UnresolvedAssertion,
  // but classification/trust must never react to it.
  const unmatchedWithContextualId = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-unmatched-with-id",
    canonical_entity_type: "model",
    canonical_id: "some-canonical-id-left-over-from-a-prior-candidate",
    status: "unmatched",
  });
  check("unmatched with a non-null contextual canonical id stays mappingState unmatched", unmatchedWithContextualId.mappingState, "unmatched");
  check("unmatched with a non-null contextual canonical id stays trustLevel none", unmatchedWithContextualId.trustLevel, "none");

  const unmatchedNoId = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-unmatched-no-id",
    canonical_entity_type: "model",
    canonical_id: null,
    status: "unmatched",
  });
  check("unmatched with no canonical id also stays mappingState unmatched", unmatchedNoId.mappingState, "unmatched");
  ok("unmatched row must NOT be treated as verified", unmatchedNoId.trustLevel !== "verified");
}

{
  // Ambiguous with a non-null contextual canonical ID remains ambiguous +
  // trust none — no winner is ever inferred from the leftover value.
  const ambiguousWithContextualId = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-ambiguous-with-id",
    canonical_entity_type: "model",
    canonical_id: "one-of-the-ambiguous-candidates",
    status: "ambiguous",
  });
  check("ambiguous with a non-null contextual canonical id stays mappingState ambiguous", ambiguousWithContextualId.mappingState, "ambiguous");
  check("ambiguous with a non-null contextual canonical id stays trustLevel none", ambiguousWithContextualId.trustLevel, "none");
}

{
  // Retired with a non-null canonical ID is the central case the contract
  // fix exists for: canonical_object_map legitimately keeps the id a
  // retired row used to resolve to, purely as historical/contextual data.
  const retiredWithContextualId = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-retired-with-id",
    canonical_entity_type: "model",
    canonical_id: "byd.byd_seal",
    status: "retired",
    notes: "superseded by a later verified mapping under a different canonical id",
  });
  check("retired with a non-null canonical id stays mappingState retired", retiredWithContextualId.mappingState, "retired");
  check("retired with a non-null canonical id stays trustLevel none", retiredWithContextualId.trustLevel, "none");
  check("retired assertion still carries the contextual canonical id as data", retiredWithContextualId.canonicalId, "byd.byd_seal");
}

{
  // A Mechanism-B 'verified' row with a null canonical_id is an invalid
  // source row (violates canonical_object_map's own check constraint).
  // Fail-closed: throw, never manufacture an id, never silently degrade to
  // unmatched.
  const invalidVerifiedRow: MechanismBRow = {
    source_table: "models",
    source_id: "legacy-model-invalid-verified",
    canonical_entity_type: "model",
    canonical_id: null,
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-08T00:00:00Z",
  };
  let threwInvalid = false;
  let threwCorrectType = false;
  try {
    assertionFromMechanismBRow(invalidVerifiedRow);
  } catch (error) {
    threwInvalid = true;
    threwCorrectType = error instanceof InvalidMechanismBRowError;
  }
  ok("a verified row with a null canonical id throws rather than producing a resolved assertion", threwInvalid);
  ok("the thrown error is specifically InvalidMechanismBRowError", threwCorrectType);

  // The batch adapter must not let one invalid row abort every other row's
  // result, and must never silently drop the invalid row either.
  const validRow: MechanismBRow = {
    source_table: "models",
    source_id: "legacy-model-valid-alongside-invalid",
    canonical_entity_type: "model",
    canonical_id: "toyota.corolla_cross",
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-08T00:00:00Z",
  };
  const batch = assertionsFromMechanismBRows([invalidVerifiedRow, validRow]);
  check("the invalid row is routed to invalidRows, not silently dropped", batch.invalidRows.length, 1);
  check("the invalid row's reason is recorded", batch.invalidRows[0]?.reason, "verified_with_null_canonical_id");
  check("the invalid row itself is preserved verbatim", batch.invalidRows[0]?.row, invalidVerifiedRow);
  check("the invalid row never becomes an assertion", batch.assertions.length, 1);
  check("the other, valid row in the same batch still converts normally", batch.assertions[0]?.externalId, "legacy-model-valid-alongside-invalid");
  check("the valid row's assertion is resolved", batch.assertions[0]?.mappingState, "resolved");
}

let threw = false;
try {
  assertionFromMechanismBRow({
    source_table: "unknown_table" as never,
    source_id: "x",
    canonical_entity_type: "model",
    canonical_id: null,
    status: "unmatched",
  });
} catch {
  threw = true;
}
ok("unrecognized source_table throws rather than guessing a normalization", threw);

// ---------------------------------------------------------------------------
// Audit classification — one scenario per required case, built from
// synthetic fixtures only. No dated live baseline counts are referenced here.
// ---------------------------------------------------------------------------

console.log("\naudit classification — comparability and trust semantics");

{
  // Exact agreement: derived model assertion and verified model assertion,
  // same external id, same canonical entity type, same canonical id.
  const [a] = assertionsFromMechanismAModels([{ canonical_id: "toyota.yaris_ativ", tdr_model_id: "legacy-model-agree" }]);
  const b = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-agree",
    canonical_entity_type: "model",
    canonical_id: "toyota.yaris_ativ",
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-10T00:00:00Z",
  });
  const report = auditAssertions([a, b]);
  const key = comparabilityKey(a);
  check("exact agreement classification", findingFor(report, key)?.classification, "exact_agreement");
  check("exact agreement finding carries both assertions", findingFor(report, key)?.assertions.length, 2);
  check("exact agreement produces no anomalies", report.anomalies.length, 0);
}

{
  // Disagreement: same comparable external identity and target entity type,
  // different canonical IDs.
  const [a] = assertionsFromMechanismAModels([{ canonical_id: "toyota.corolla_cross", tdr_model_id: "legacy-model-disagree" }]);
  const b = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-disagree",
    canonical_entity_type: "model",
    canonical_id: "toyota.corolla_altis",
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-10T00:00:00Z",
  });
  const report = auditAssertions([a, b]);
  const key = comparabilityKey(a);
  check("disagreement classification", findingFor(report, key)?.classification, "disagreement");
}

{
  // Derived only: Mechanism A resolves an identity and no Mechanism-B
  // counterpart exists at all (not present, not unmatched — simply absent).
  const [a] = assertionsFromMechanismAModels([{ canonical_id: "honda.civic", tdr_model_id: "legacy-model-derived-only" }]);
  const report = auditAssertions([a]);
  const key = comparabilityKey(a);
  check("derived-only classification", findingFor(report, key)?.classification, "derived_only");
}

{
  // Verified only: Mechanism B has a verified comparable assertion and
  // Mechanism A does not.
  const b = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-verified-only",
    canonical_entity_type: "model",
    canonical_id: "jaecoo.jaecoo_5_ev",
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-08T00:00:00Z",
  });
  const report = auditAssertions([b]);
  const key = comparabilityKey(b);
  check("verified-only classification", findingFor(report, key)?.classification, "verified_only");
}

{
  // Ambiguous mechanism-B state must remain ambiguous even when Mechanism A
  // has a derived opinion — no winner may be inferred.
  const [a] = assertionsFromMechanismAModels([{ canonical_id: "mg.mg4", tdr_model_id: "legacy-model-ambiguous" }]);
  const b = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-ambiguous",
    canonical_entity_type: "model",
    canonical_id: null,
    status: "ambiguous",
  });
  const report = auditAssertions([a, b]);
  const key = comparabilityKey(a);
  check("ambiguous mechanism-B state stays ambiguous, A present", findingFor(report, key)?.classification, "mechanism_b_ambiguous");

  const reportBOnly = auditAssertions([b]);
  check("ambiguous mechanism-B state stays ambiguous, A absent", findingFor(reportBOnly, key)?.classification, "mechanism_b_ambiguous");
}

{
  // Retired mechanism-B state must remain explicitly retired.
  const b = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-retired",
    canonical_entity_type: "model",
    canonical_id: "byd.byd_seal",
    status: "retired",
    notes: "superseded by a later verified mapping under a different canonical id",
  });
  const report = auditAssertions([b]);
  const key = comparabilityKey(b);
  check("retired mechanism-B state classification", findingFor(report, key)?.classification, "mechanism_b_retired");
}

{
  // Unmatched mechanism-B state, surfaced as its own classification (not
  // silently folded into derived-only) even when A also has an opinion.
  const [a] = assertionsFromMechanismAModels([{ canonical_id: "isuzu.dmax", tdr_model_id: "legacy-model-unmatched" }]);
  const b = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-unmatched",
    canonical_entity_type: "model",
    canonical_id: null,
    status: "unmatched",
  });
  const report = auditAssertions([a, b]);
  const key = comparabilityKey(a);
  check("unmatched mechanism-B state classification, A present", findingFor(report, key)?.classification, "mechanism_b_unmatched");
}

{
  // Non-comparable target level: the same external model UUID has a
  // Mechanism-A model->model assertion and a Mechanism-B model->generation
  // assertion. These must land in two separate findings, and neither may be
  // classified as a disagreement.
  const sharedExternalId = "legacy-model-multi-scope";
  const [a] = assertionsFromMechanismAModels([{ canonical_id: "jaecoo.jaecoo_5_ev", tdr_model_id: sharedExternalId }]);
  const bModel = assertionFromMechanismBRow({
    source_table: "models",
    source_id: sharedExternalId,
    canonical_entity_type: "model",
    canonical_id: "jaecoo.jaecoo_5_ev",
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-08T00:00:00Z",
  });
  const bGeneration = assertionFromMechanismBRow({
    source_table: "models",
    source_id: sharedExternalId,
    canonical_entity_type: "generation",
    canonical_id: "jaecoo.jaecoo_5_ev.gen1",
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-08T00:00:00Z",
  });
  const report = auditAssertions([a, bModel, bGeneration]);

  const modelFinding = findingFor(report, comparabilityKey(a));
  const generationFinding = findingFor(report, comparabilityKey(bGeneration));

  check("model-scope finding is exact agreement, not merged with generation scope", modelFinding?.classification, "exact_agreement");
  check("generation-scope finding is its own group", generationFinding?.classification, "verified_only");
  ok(
    "neither finding is ever classified as a disagreement merely for sharing an external id",
    modelFinding?.classification !== "disagreement" && generationFinding?.classification !== "disagreement",
  );
  check(
    "model-scope finding records the sibling generation scope for visibility",
    modelFinding?.otherCanonicalEntityTypesForSameExternalId,
    ["generation"],
  );
  check(
    "generation-scope finding records the sibling model scope for visibility",
    generationFinding?.otherCanonicalEntityTypesForSameExternalId,
    ["model"],
  );
  check("exactly two findings were produced for this external id", report.findings.length, 2);
}

{
  // Trust non-escalation: a derived assertion agreeing with a verified
  // assertion must remain "derived" in its own assertion — agreement must
  // never mutate or upgrade its trust level.
  const [a] = assertionsFromMechanismAModels([{ canonical_id: "toyota.hilux_revo_double_cab", tdr_model_id: "legacy-model-trust" }]);
  const b = assertionFromMechanismBRow({
    source_table: "models",
    source_id: "legacy-model-trust",
    canonical_entity_type: "model",
    canonical_id: "toyota.hilux_revo_double_cab",
    status: "verified",
    verified_by: "reviewer@example.com",
    verified_at: "2026-09-08T00:00:00Z",
  });
  const report = auditAssertions([a, b]);
  const finding = findingFor(report, comparabilityKey(a));
  const mechanismAInFinding = finding?.assertions.find((x) => x.provenance.mechanism === "mechanism_a_release_crosswalk");
  const mechanismBInFinding = finding?.assertions.find((x) => x.provenance.mechanism === "mechanism_b_canonical_object_map");
  check("finding classification is exact agreement", finding?.classification, "exact_agreement");
  check("mechanism A assertion trust level is untouched by agreement", mechanismAInFinding?.trustLevel, "derived");
  check("mechanism B assertion trust level is untouched by agreement", mechanismBInFinding?.trustLevel, "verified");
  ok("original input assertion object was not mutated", a.trustLevel === "derived");
}

// ---------------------------------------------------------------------------
// Duplicate-mechanism-assertion anomalies — a comparability group must never
// silently pick a "first row" winner when the same mechanism asserts more
// than once under one key.
// ---------------------------------------------------------------------------

console.log("\nduplicate mechanism assertions — surfaced as anomalies, never silently selected");

{
  // Duplicate Mechanism A, same target: two rows that happen to agree.
  // Agreement does not excuse the duplication from being reported.
  const sameExternalId = "legacy-model-dup-a-same-target";
  const duplicateSameTarget: ExternalIdentityAssertion[] = [
    ...assertionsFromMechanismAModels([{ canonical_id: "toyota.yaris_ativ", tdr_model_id: sameExternalId }]),
    ...assertionsFromMechanismAModels([{ canonical_id: "toyota.yaris_ativ", tdr_model_id: sameExternalId }]),
  ];
  const report = auditAssertions(duplicateSameTarget);
  const key = comparabilityKey(duplicateSameTarget[0]);
  ok("duplicate mechanism-A group (same target) produces no finding", findingFor(report, key) === undefined);
  check("duplicate mechanism-A group (same target) produces exactly one anomaly", report.anomalies.length, 1);
  check("the anomaly names mechanism A", report.anomalies[0]?.mechanism, "mechanism_a_release_crosswalk");
  check("the anomaly type is duplicate_mechanism_assertions", report.anomalies[0]?.type, "duplicate_mechanism_assertions");
  check("the anomaly preserves both duplicate rows", report.anomalies[0]?.assertions.length, 2);
  check("summary counts the anomaly", report.summary.totalAnomalies, 1);
}

{
  // Duplicate Mechanism A, conflicting targets: two rows for the same
  // external id that disagree about the canonical id. Still an anomaly, not
  // a "disagreement" classification, and neither is picked as the answer.
  const sameExternalId = "legacy-model-dup-a-conflicting-targets";
  const duplicateConflicting: ExternalIdentityAssertion[] = [
    ...assertionsFromMechanismAModels([{ canonical_id: "toyota.yaris_ativ", tdr_model_id: sameExternalId }]),
    ...assertionsFromMechanismAModels([{ canonical_id: "toyota.corolla_cross", tdr_model_id: sameExternalId }]),
  ];
  const report = auditAssertions(duplicateConflicting);
  const key = comparabilityKey(duplicateConflicting[0]);
  ok("duplicate mechanism-A group (conflicting targets) produces no finding", findingFor(report, key) === undefined);
  ok(
    "duplicate mechanism-A group (conflicting targets) is never classified as a disagreement",
    !report.findings.some((f) => f.comparabilityKey === key),
  );
  check("duplicate mechanism-A group (conflicting targets) produces exactly one anomaly", report.anomalies.length, 1);
  const conflictingIds = report.anomalies[0]?.assertions.map((a) => a.canonicalId).sort();
  check("the anomaly preserves both conflicting canonical ids, neither dropped", conflictingIds, ["toyota.corolla_cross", "toyota.yaris_ativ"]);
}

{
  // Duplicate Mechanism B despite the live database uniqueness constraint:
  // the audit engine must not assume the constraint holds and must not
  // crash or silently collapse the duplicate if it is ever violated.
  const sameExternalId = "legacy-model-dup-b";
  const duplicateB: MechanismBRow[] = [
    {
      source_table: "models", source_id: sameExternalId, canonical_entity_type: "model",
      canonical_id: "mg.mg4", status: "verified", verified_by: "reviewer-one@example.com", verified_at: "2026-09-08T00:00:00Z",
    },
    {
      source_table: "models", source_id: sameExternalId, canonical_entity_type: "model",
      canonical_id: "mg.mg5", status: "verified", verified_by: "reviewer-two@example.com", verified_at: "2026-09-09T00:00:00Z",
    },
  ];
  const { assertions: bAssertions } = assertionsFromMechanismBRows(duplicateB);
  const report = auditAssertions(bAssertions);
  const key = comparabilityKey(bAssertions[0]);
  ok("duplicate mechanism-B group produces no finding", findingFor(report, key) === undefined);
  check("duplicate mechanism-B group produces exactly one anomaly", report.anomalies.length, 1);
  check("the anomaly names mechanism B", report.anomalies[0]?.mechanism, "mechanism_b_canonical_object_map");
  check("the anomaly preserves both duplicate mechanism-B rows", report.anomalies[0]?.assertions.length, 2);
}

{
  // Both mechanisms duplicated in the same group at once.
  const sameExternalId = "legacy-model-dup-both";
  const assertions: ExternalIdentityAssertion[] = [
    ...assertionsFromMechanismAModels([{ canonical_id: "gwm.haval_h6", tdr_model_id: sameExternalId }]),
    ...assertionsFromMechanismAModels([{ canonical_id: "gwm.haval_jolion", tdr_model_id: sameExternalId }]),
    assertionFromMechanismBRow({
      source_table: "models", source_id: sameExternalId, canonical_entity_type: "model",
      canonical_id: "gwm.haval_h6", status: "verified", verified_by: "r1", verified_at: "2026-09-08T00:00:00Z",
    }),
    assertionFromMechanismBRow({
      source_table: "models", source_id: sameExternalId, canonical_entity_type: "model",
      canonical_id: "gwm.haval_jolion", status: "verified", verified_by: "r2", verified_at: "2026-09-09T00:00:00Z",
    }),
  ];
  const report = auditAssertions(assertions);
  check("both mechanisms duplicated produces two anomalies, one per mechanism", report.anomalies.length, 2);
  check(
    "anomaly mechanisms are exactly mechanism A and mechanism B",
    report.anomalies.map((a) => a.mechanism).sort(),
    ["mechanism_a_release_crosswalk", "mechanism_b_canonical_object_map"],
  );
  check("the whole group is excluded from findings when both mechanisms are duplicated", report.findings.length, 0);
}

{
  // Deterministic anomaly ordering: shuffling the input must not change the
  // order anomalies are reported in.
  const idOne = "legacy-model-dup-order-1";
  const idTwo = "legacy-model-dup-order-2";
  const build = (): ExternalIdentityAssertion[] => [
    ...assertionsFromMechanismAModels([{ canonical_id: "a.one", tdr_model_id: idTwo }]),
    ...assertionsFromMechanismAModels([{ canonical_id: "a.two", tdr_model_id: idTwo }]),
    ...assertionsFromMechanismAModels([{ canonical_id: "b.one", tdr_model_id: idOne }]),
    ...assertionsFromMechanismAModels([{ canonical_id: "b.two", tdr_model_id: idOne }]),
  ];
  const inOrder = auditAssertions(build());
  const shuffled = auditAssertions([...build()].reverse());
  check(
    "anomaly order is identical regardless of input order",
    shuffled.anomalies.map((a) => a.comparabilityKey),
    inOrder.anomalies.map((a) => a.comparabilityKey),
  );
  check("anomaly contents are identical regardless of input order", shuffled.anomalies, inOrder.anomalies);
}

// ---------------------------------------------------------------------------
// Deterministic output (findings + summary + anomalies)
// ---------------------------------------------------------------------------

console.log("\ndeterministic output — order-independent");

{
  const brandRows = [
    { canonical_id: "toyota", tdr_brand_id: "brand-1" },
    { canonical_id: "honda", tdr_brand_id: "brand-2" },
    { canonical_id: "isuzu", tdr_brand_id: "brand-3" },
  ];
  const modelRows = [
    { canonical_id: "toyota.yaris_ativ", tdr_model_id: "model-1" },
    { canonical_id: "honda.civic", tdr_model_id: "model-2" },
  ];
  const mapRows: MechanismBRow[] = [
    { source_table: "models", source_id: "model-1", canonical_entity_type: "model", canonical_id: "toyota.yaris_ativ", status: "verified", verified_by: "r", verified_at: "2026-09-01T00:00:00Z" },
    { source_table: "models", source_id: "model-2", canonical_entity_type: "model", canonical_id: null, status: "unmatched" },
    { source_table: "models", source_id: "model-3", canonical_entity_type: "model", canonical_id: null, status: "ambiguous" },
    { source_table: "trims", source_id: "trim-1", canonical_entity_type: "market_trim", canonical_id: "toyota.yaris_ativ.g1.trim.x", status: "retired" },
  ];

  const buildAssertions = (
    brands: typeof brandRows,
    models: typeof modelRows,
    maps: MechanismBRow[],
  ): ExternalIdentityAssertion[] => [
    ...assertionsFromMechanismABrands(brands),
    ...assertionsFromMechanismAModels(models),
    ...assertionsFromMechanismBRows(maps).assertions,
  ];

  const inOrder = auditAssertions(buildAssertions(brandRows, [...modelRows], [...mapRows]));
  const shuffled = auditAssertions(
    buildAssertions([...brandRows].reverse(), [...modelRows].reverse(), [...mapRows].reverse()),
  );

  check("finding order is identical regardless of input order", shuffled.findings.map((f) => f.comparabilityKey), inOrder.findings.map((f) => f.comparabilityKey));
  check("summary is identical regardless of input order", shuffled.summary, inOrder.summary);
  check("anomalies are identical (empty) regardless of input order", shuffled.anomalies, inOrder.anomalies);
  check("non-empty classification distribution sanity", classificationCounts(inOrder), {
    exact_agreement: 1,
    // brand-1/brand-2/brand-3 each have a Mechanism A assertion with no
    // Mechanism B counterpart at brand scope (Mechanism B is only ever
    // observed for models/model_powertrains/trims in this fixture).
    derived_only: 3,
    mechanism_b_unmatched: 1,
    mechanism_b_ambiguous: 1,
    mechanism_b_retired: 1,
  });
}

console.log(failed ? `\n${failed} check(s) failed` : "\nall external-identity audit checks passed");
process.exit(failed ? 1 : 0);
