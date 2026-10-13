"""R6 scoped Crosswalk v2 pure resolver regressions: no DB/network/writer."""
import pytest

from vehreg.ice_scoped_crosswalk import (
    IceFact, LegacyLink, OwnerScope, ScopedCrosswalk, normalize_reg_type, summarize,
)


def owner(group, reg, action, target=None, ref="frozen-owner-audit:001"):
    return OwnerScope(group, reg, action, target, ref, "7.0")


def engine(approved, legacy=(), materialized=()):
    return ScopedCrosswalk(approved, legacy, materialized, "7.0")


def test_many_ice_groups_can_approve_one_canonical_without_losing_units():
    matcher = engine([owner("vigo-kun15", "ALL", "APPROVED", "toyota.vigo"),
                      owner("vigo-tgn16", "ALL", "APPROVED", "toyota.vigo")],
                     materialized=["toyota.vigo"])
    rows = matcher.resolve_all([IceFact("vigo-kun15", "RY1", 32),
                                IceFact("vigo-tgn16", "รย.3", 18)])
    assert [r.canonical_id for r in rows] == ["toyota.vigo", "toyota.vigo"]
    assert summarize(rows)["approved_or_legacy_active_covered_units"] == 50


def test_pickup_class_resolution_requires_explicit_ry2():
    matcher = engine([
        owner("mitsubishi-triton", "ALL", "PENDING"),
        owner("mitsubishi-triton", "RY1", "APPROVED", "mitsubishi.triton_double_cab"),
        owner("mitsubishi-triton", "RY2", "APPROVED", "mitsubishi.triton_double_cab"),
        owner("mitsubishi-triton", "RY3", "APPROVED", "mitsubishi.triton_cab"),
    ], materialized=["mitsubishi.triton_double_cab", "mitsubishi.triton_cab"])
    rows = matcher.resolve_all([IceFact("mitsubishi-triton", "รย.1", 60),
                                IceFact("mitsubishi-triton", "รย.2", 4),
                                IceFact("mitsubishi-triton", "รย.3", 39),
                                IceFact("mitsubishi-triton", "รย.10", 2)])
    assert [r.canonical_id for r in rows] == [
        "mitsubishi.triton_double_cab", "mitsubishi.triton_double_cab",
        "mitsubishi.triton_cab", None,
    ]
    assert rows[-1].disposition == "OWNER_PENDING"
    assert summarize(rows)["approved_or_legacy_active_covered_units"] == 103


def test_owner_exclusion_blocks_legacy_and_does_not_change_fixed_denominator():
    matcher = engine([owner("honda-e", "ALL", "EXCLUDED")],
                     [LegacyLink("honda-e", "honda.en2", "AUTO")], ["honda.en2"])
    result = matcher.resolve(IceFact("honda-e", "รย.1", 10))
    assert result.disposition == "OWNER_EXCLUDED" and result.canonical_id is None
    summary = summarize([result])
    assert summary["fixed_denominator"] == 10
    assert summary["owner_excluded_units"] == 10
    assert summary["adjusted_denominator"] == 0
    assert summary["approved_or_legacy_active_covered_units"] == 0


def test_serena_owner_link_precedes_series_and_legacy_proposal():
    matcher = engine([owner("nissan-serena", "ALL", "APPROVED", "nissan.serena")],
                     [LegacyLink("nissan-serena", "nissan.other", "PROPOSED")],
                     ["nissan.serena", "nissan.other"])
    out = matcher.resolve(IceFact("nissan-serena", "RY1", 3584))
    assert (out.disposition, out.canonical_id) == ("OWNER_APPROVED", "nissan.serena")


def test_unmaterialized_identity_is_pending_not_a_new_owner_review():
    matcher = engine([owner("hino-new", "ALL", "APPROVED", "hino.xzu")])
    result = matcher.resolve(IceFact("hino-new", "รย.3", 2600))
    assert result.canonical_id is None
    assert result.disposition == "PENDING_MATERIALIZATION"


def test_legacy_ambiguity_does_not_pick_arbitrary_model():
    matcher = engine([], [LegacyLink("a", "bmw.3", "AUTO"),
                         LegacyLink("a", "bmw.5", "APPROVED")], ["bmw.3", "bmw.5"])
    assert matcher.resolve(IceFact("a", "RY1", 5)).disposition == "AMBIGUOUS_LEGACY_ACTIVE"


def test_proposed_never_contributes_to_approved_coverage():
    matcher = engine([], [LegacyLink("one", "toyota.yaris", "AUTO"),
                         LegacyLink("two", "toyota.camry", "PROPOSED")],
                     ["toyota.yaris", "toyota.camry"])
    rows = matcher.resolve_all([IceFact("one", "RY1", 99),
                                IceFact("two", "RY1", 120)])
    assert rows[0].disposition == "LEGACY_ACTIVE"
    assert rows[1].disposition == "UNMATCHED"
    assert summarize(rows)["fixed_denominator_coverage_pct"] == pytest.approx(100 * 99 / 219)


def test_duplicate_owner_decisions_and_missing_provenance_fail():
    with pytest.raises(ValueError, match="duplicate owner decision"):
        engine([owner("g", "RY1", "APPROVED", "car.a"),
                owner("g", "รย.1", "APPROVED", "car.b")])
    with pytest.raises(ValueError, match="audit decision_ref"):
        engine([owner("g", "ALL", "APPROVED", "car.a", ref="")])


def test_stale_master_version_and_invalid_reg_scope_fail():
    with pytest.raises(ValueError, match="belongs to"):
        engine([OwnerScope("g", "ALL", "APPROVED", "car.a", "signed", "6.0")])
    with pytest.raises(ValueError, match="Invalid registration type"):
        normalize_reg_type("3")
    assert normalize_reg_type("RY2") == "รย.2"
    assert normalize_reg_type("รย.3") == "รย.3"


def test_duplicate_registration_grain_fails_instead_of_double_counting():
    matcher = engine([])
    with pytest.raises(ValueError, match="Duplicate Ice aggregate grain"):
        matcher.resolve_all([IceFact("g", "RY1", 3), IceFact("g", "รย.1", 7)])


def test_exact_exclusion_overrides_all_scope():
    matcher = engine([owner("g", "ALL", "APPROVED", "car.a"),
                      owner("g", "RY3", "EXCLUDED")], materialized=["car.a"])
    rows = matcher.resolve_all([IceFact("g", "RY1", 10),
                                IceFact("g", "RY3", 5)])
    assert [r.disposition for r in rows] == ["OWNER_APPROVED", "OWNER_EXCLUDED"]
    summary = summarize(rows)
    assert summary["fixed_denominator"] == 15
    assert summary["approved_or_legacy_active_covered_units"] == 10


def test_ry2_never_automatically_relabels_to_ry1():
    matcher = engine([owner("g", "RY1", "APPROVED", "pickup.double")],
                     materialized=["pickup.double"])
    assert matcher.resolve(IceFact("g", "RY2", 22)).disposition == "UNMATCHED"


def test_scoped_only_pickup_cannot_inherit_all_or_legacy_parent():
    matcher = ScopedCrosswalk(
        [owner("triton", "ALL", "APPROVED", "mitsubishi.triton_double_cab"),
         owner("triton", "RY1", "APPROVED", "mitsubishi.triton_double_cab")],
        [LegacyLink("triton", "mitsubishi.triton_double_cab", "AUTO")],
        ["mitsubishi.triton_double_cab"], "7.0", scoped_only_groups={"triton"},
    )
    assert matcher.resolve(IceFact("triton", "RY1", 50)).disposition == "OWNER_APPROVED"
    assert matcher.resolve(IceFact("triton", "RY3", 40)).disposition == "SCOPED_CLASS_UNRESOLVED"
