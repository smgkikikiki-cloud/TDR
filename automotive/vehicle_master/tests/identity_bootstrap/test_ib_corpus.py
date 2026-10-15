"""The golden corpus is the executable specification of the engine that does not exist yet.

The reference oracle (ib_reference.py) executes SPEC.md; the corpus expectations were written by hand. These tests prove the two agree, that
the corpus covers the taxonomy, every reason code and every scenario the brief required, and that nothing is asserted vacuously.
"""
from __future__ import annotations

import pytest

import ib_support as S

CASES = S.cases()
CODES = S.codes()


@pytest.mark.parametrize("impl", sorted(S.IMPLS))
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_implementation_reproduces_the_expectation(case, impl):
    assert S.RUNNERS[case["kind"]](case, impl) == []


def asserted_codes():
    out = set()
    for c in CASES:
        if c["kind"] != "decide":
            continue
        exp = c["expect"]
        if "refusal" in exp:
            out.add(exp["refusal"])
            continue
        for want in exp["decisions"].values():
            out |= set(want.get("reason_codes", []))
            if "primary_reason" in want:
                out.add(want["primary_reason"])
    return out


def test_every_reason_code_is_asserted_by_some_case():
    missing = set(CODES) - asserted_codes()
    assert not missing, f"codes no corpus case asserts: {sorted(missing)}"


def test_every_taxonomy_entry_is_covered_and_every_case_cites_real_entries():
    ids = {e["id"] for e in S.taxonomy()["entries"]}
    cited = {t for c in CASES for t in c["taxonomy"]}
    assert cited <= ids, sorted(cited - ids)
    assert ids <= cited, sorted(ids - cited)


def test_corpus_exercises_every_outcome_and_every_input_kind():
    outcomes = {w["outcome"] for c in CASES if c["kind"] == "decide" and "decisions" in c["expect"] for w in c["expect"]["decisions"].values()}
    assert outcomes == set(S.OUTCOMES)
    assert {c["kind"] for c in CASES} == {"decide", "apply", "allocate", "lifecycle"}
    assert {c["origin"] for c in CASES} == {"task_example", "ice_m7_data", "design"}


REQUIRED_SCENARIOS = {          # the brief's golden edge cases -> the case that pins each one
    "genuinely new clean model": "new.clean-model",
    "new model with very low registration volume": "new.low-volume",
    "high-volume raw unresolved identity": "subject.raw-high-volume",
    "exact duplicate of an existing model": "dup.exact-existing",
    "spelling variant": "dup.spelling-variant",
    "alias/rebadge": "dup.alias-rebadge-brand-relabel",
    "rebadge across brands is separate": "new.rebadge-other-brand",
    "new generation of existing nameplate": "relation.generation-of-existing",
    "trim mistaken for model": "relation.trim-of-existing",
    "model code mistaken for model": "shape.model-code",
    "body variant": "relation.body-variant-of-existing",
    "provider finer than TDR": "granularity.provider-finer",
    "provider coarser than TDR": "granularity.provider-coarser",
    "rename": "lineage.rename-keeps-identity",
    "merge": "lineage.merge-bound-to-many",
    "split": "lineage.split-child-of-bound-parent",
    "split cycle": "lineage.split-cycle",
    "provisional identity": "subject.provisional",
    "unknown brand": "brand.unknown",
    "known brand / unknown model": "new.clean-model",
    "same model discovered from two providers": "batch.two-providers-one-identity",
    "simultaneous duplicate discovery": "apply.simultaneous-same-subject",
    "simultaneous different spelling": "apply.simultaneous-different-spelling",
    "existing DISCOVERED identity seen again": "state.already-discovered-binding",
    "existing canonical identity created after discovery began": "apply.admin-created-it-first",
    "canonical ID collision": "id.collision-with-different-identity",
    "source version changes": "state.source-version-changes",
    "external ID changes but lineage preserves identity": "lineage.rename-with-new-name",
    "NISSAN|BVL2RTYD23FHP A": "subject.raw-high-volume",
    "Mercedes E300": "shape.model-code-brand-prefixed",
    "Honda City Hatchback": "granularity.provider-finer",
    "Hilux Revo Double Cab": "relation.body-variant-of-existing",
    "City and City Hatchback in one batch": "batch.city-and-city-hatchback",
    "ไม่ระบุ": "subject.unspecified-name",
}


def test_every_scenario_the_brief_requires_has_a_case():
    ids = {c["id"] for c in CASES}
    for scenario, case_id in REQUIRED_SCENARIOS.items():
        assert case_id in ids, f"{scenario}: no case {case_id}"


def test_the_brief_examples_do_not_blindly_create_a_model():
    for case_id, sid in [("subject.raw-high-volume", "ice:NISSAN|BVL2RTYD23FHP A"), ("shape.model-code-brand-prefixed", "ice:mercedes-e300"),
                         ("granularity.provider-finer", "ice:honda-city-hatchback"), ("relation.body-variant-of-existing", "ice:toyota-hilux-revo-double-cab")]:
        got = S.by_subject(S.run_decide(S.case_by_id(case_id)["input"]))[sid]
        assert got["outcome"] != "CREATE_IDENTITY", case_id
        assert got["write_plan"] is None and got["identity"] is None


def test_creations_in_the_corpus_are_a_minority_and_all_justified():
    creates = reviews = holds = 0
    for c in CASES:
        if c["kind"] == "decide" and "decisions" in c["expect"]:
            for w in c["expect"]["decisions"].values():
                creates += w["outcome"] == "CREATE_IDENTITY"
                reviews += w["outcome"] == "IDENTITY_REVIEW"
                holds += w["outcome"] == "HOLD"
    assert creates < reviews + holds, "the corpus must lean towards refusing; a corpus that mostly creates tests nothing"


def test_expectations_are_not_vacuous():
    for c in CASES:
        if c["kind"] == "decide" and "decisions" in c["expect"]:
            for sid, want in c["expect"]["decisions"].items():
                assert "primary_reason" in want and "reason_codes" in want, (c["id"], sid)
