import {
  auditAssertions,
  type AuditClassification,
} from "../lib/external-identity/audit.ts";
import {
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
// Mechanism adapters — source_table normalization and derived/skip rules
// ---------------------------------------------------------------------------

console.log("mechanism adapters — normalization and skip rules");

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

const unmatchedBRow: MechanismBRow = {
  source_table: "models",
  source_id: "legacy-model-1",
  canonical_entity_type: "model",
  canonical_id: null,
  status: "unmatched",
};
const unmatchedAssertion = assertionFromMechanismBRow(unmatchedBRow);
check("unmatched mechanism B row maps to mappingState unmatched", unmatchedAssertion.mappingState, "unmatched");
ok("unmatched mechanism B row must NOT be treated as verified", unmatchedAssertion.trustLevel !== "verified");
check("unmatched mechanism B row trustLevel is none", unmatchedAssertion.trustLevel, "none");

let threw = false;
try {
  assertionFromMechanismBRow({ ...unmatchedBRow, source_table: "unknown_table" as never });
} catch {
  threw = true;
}
ok("unrecognized source_table throws rather than guessing a normalization", threw);

// ---------------------------------------------------------------------------
// Audit classification — one scenario per required case, built from
// synthetic fixtures only. The 2026-09-15 dated baseline counts are never
// referenced here.
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
// Deterministic output
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
    ...assertionsFromMechanismBRows(maps),
  ];

  const inOrder = auditAssertions(buildAssertions(brandRows, [...modelRows], [...mapRows]));
  const shuffled = auditAssertions(
    buildAssertions([...brandRows].reverse(), [...modelRows].reverse(), [...mapRows].reverse()),
  );

  check("finding order is identical regardless of input order", shuffled.findings.map((f) => f.comparabilityKey), inOrder.findings.map((f) => f.comparabilityKey));
  check("summary is identical regardless of input order", shuffled.summary, inOrder.summary);
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
