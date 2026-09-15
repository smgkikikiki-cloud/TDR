"""registration_v2_parity: volume/identity/coverage/grain parity, kept
strictly separate per the packet's own distinction - a mapping disagreement
is not automatically a unit mismatch."""

import unittest

from vehreg.registration_v2_parity import (
    CoverageParity,
    LegacyRegistrationRow,
    V2FactRow,
    V2ObservationRow,
    build_parity_report,
    classify_pairs,
    coverage_parity,
    find_duplicate_source_refs,
    find_reconciliation_failures,
    model_component,
    volume_parity,
)


def _legacy(id_, period, reg_type, units, model_id=None, brand="", model=""):
    return LegacyRegistrationRow(id=id_, period=period, registration_type=reg_type,
                                 brand_name_raw=brand, model_name_raw=model,
                                 model_id=model_id, units=units)


def _v2_obs(obs_id, source_kind, source_ref, period, reg_type, units):
    return V2ObservationRow(observation_id=obs_id, source_kind=source_kind,
                            source_ref=source_ref, period=period,
                            registration_type=reg_type, units=units)


def _v2_fact(obs_id, canonical_id, grain, units):
    return V2FactRow(observation_id=obs_id, canonical_id=canonical_id,
                     grain=grain, units=units)


BACKFILL = "legacy_registrations_backfill"


class ModelComponentTests(unittest.TestCase):
    def test_model_grain_id_is_unchanged(self):
        self.assertEqual(model_component("toyota.yaris_ativ"), "toyota.yaris_ativ")

    def test_variant_grain_id_is_truncated_to_model(self):
        self.assertEqual(
            model_component("toyota.yaris_ativ.gen1.smart_1_2"),
            "toyota.yaris_ativ")

    def test_brand_grain_id_is_unchanged(self):
        self.assertEqual(model_component("toyota"), "toyota")


class VolumeParityTests(unittest.TestCase):
    def test_volume_by_period_matches_when_totals_agree(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100)]
        v2 = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        result = volume_parity(legacy, v2, by="period")
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].matches)
        self.assertEqual(result[0].difference, 0)

    def test_volume_by_period_flags_a_real_mismatch(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100)]
        v2 = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 90)]
        result = volume_parity(legacy, v2, by="period")
        self.assertFalse(result[0].matches)
        self.assertEqual(result[0].difference, -10)

    def test_volume_by_registration_type(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100),
                 _legacy("b", "2026-01", "RY3", 40)]
        v2 = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100),
             _v2_obs("o2", BACKFILL, "b", "2026-01", "RY3", 40)]
        result = volume_parity(legacy, v2, by="registration_type")
        self.assertEqual({r.key: r.v1_units for r in result},
                         {"RY1": 100, "RY3": 40})

    def test_invalid_by_argument_raises(self):
        with self.assertRaises(ValueError):
            volume_parity([], [], by="brand")


class CoverageParityTests(unittest.TestCase):
    def test_coverage_totals(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="m1"),
                 _legacy("b", "2026-01", "RY1", 50, model_id=None)]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100),
                 _v2_obs("o2", BACKFILL, "b", "2026-01", "RY1", 50)]
        v2_facts = [_v2_fact("o1", "acme.gecko", "MODEL", 100)]
        coverage = coverage_parity(legacy, v2_obs, v2_facts)
        self.assertEqual(coverage.v1_total_units, 150)
        self.assertEqual(coverage.v1_mapped_units, 100)
        self.assertEqual(coverage.v2_total_units, 150)
        self.assertEqual(coverage.v2_resolved_units, 100)
        self.assertAlmostEqual(coverage.v1_mapped_pct, 66.6667, places=3)
        self.assertAlmostEqual(coverage.v2_resolved_pct, 66.6667, places=3)


class PairClassificationTests(unittest.TestCase):
    def test_agree_when_crosswalked_model_matches_v2_model_grain(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        facts = {"o1": _v2_fact("o1", "acme.gecko", "MODEL", 100)}
        crosswalk = {"uuid-1": "acme.gecko"}
        result = classify_pairs(legacy, v2_obs, facts, crosswalk)
        self.assertEqual(result.classifications[0].classification, "agree")

    def test_agree_when_v2_resolved_to_a_variant_of_the_same_model(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        facts = {"o1": _v2_fact("o1", "acme.gecko.gen1.lx", "VARIANT", 100)}
        crosswalk = {"uuid-1": "acme.gecko"}
        result = classify_pairs(legacy, v2_obs, facts, crosswalk)
        self.assertEqual(result.classifications[0].classification, "agree")

    def test_identity_disagreement_when_models_differ(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        facts = {"o1": _v2_fact("o1", "acme.falcon_one", "MODEL", 100)}
        crosswalk = {"uuid-1": "acme.gecko"}
        result = classify_pairs(legacy, v2_obs, facts, crosswalk)
        self.assertEqual(result.classifications[0].classification,
                         "identity_disagreement")

    def test_grain_difference_v2_coarser_same_brand(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        facts = {"o1": _v2_fact("o1", "acme", "BRAND", 100)}
        crosswalk = {"uuid-1": "acme.gecko"}
        result = classify_pairs(legacy, v2_obs, facts, crosswalk)
        self.assertEqual(result.classifications[0].classification,
                         "grain_difference_v2_coarser")

    def test_brand_grain_disagreement_is_not_coarser(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        facts = {"o1": _v2_fact("o1", "otherbrand", "BRAND", 100)}
        crosswalk = {"uuid-1": "acme.gecko"}
        result = classify_pairs(legacy, v2_obs, facts, crosswalk)
        self.assertEqual(result.classifications[0].classification,
                         "identity_disagreement")

    def test_resolution_coverage_v1_only(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        crosswalk = {"uuid-1": "acme.gecko"}
        result = classify_pairs(legacy, v2_obs, {}, crosswalk)
        self.assertEqual(result.classifications[0].classification,
                         "resolution_coverage_v1_only")

    def test_resolution_coverage_v2_only(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id=None)]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        facts = {"o1": _v2_fact("o1", "acme.gecko", "MODEL", 100)}
        result = classify_pairs(legacy, v2_obs, facts, {})
        self.assertEqual(result.classifications[0].classification,
                         "resolution_coverage_v2_only")

    def test_v1_uncrosswalked_is_its_own_bucket(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-unknown")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        facts = {"o1": _v2_fact("o1", "acme.gecko", "MODEL", 100)}
        result = classify_pairs(legacy, v2_obs, facts, {})  # empty crosswalk
        self.assertEqual(result.classifications[0].classification,
                         "v1_uncrosswalked")

    def test_both_unresolved(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id=None)]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        result = classify_pairs(legacy, v2_obs, {}, {})
        self.assertEqual(result.classifications[0].classification,
                         "both_unresolved")

    def test_legacy_row_not_yet_backfilled_is_reported_separately(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        result = classify_pairs(legacy, [], {}, {"uuid-1": "acme.gecko"})
        self.assertEqual(result.classifications, [])
        self.assertEqual(result.legacy_rows_missing_v2_backfill, ["a"])

    def test_orphaned_v2_backfill_observation_is_reported_separately(self):
        v2_obs = [_v2_obs("o1", BACKFILL, "gone", "2026-01", "RY1", 100)]
        result = classify_pairs([], v2_obs, {}, {})
        self.assertEqual(result.v2_orphaned_backfill_observations, ["o1"])

    def test_non_backfill_v2_observations_never_enter_pairing(self):
        # A DLT-forward-ingested v2 observation (no v1 counterpart at all)
        # must never be treated as an orphan or a pair - it simply isn't
        # part of the v1<->v2 comparison.
        v2_obs = [_v2_obs("o1", "dlt_csv", "file:0", "2027-01", "RY1", 100)]
        result = classify_pairs([], v2_obs, {}, {})
        self.assertEqual(result.v2_orphaned_backfill_observations, [])
        self.assertEqual(result.classifications, [])


class DuplicateAndReconciliationTests(unittest.TestCase):
    def test_no_duplicates_in_normal_operation(self):
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100),
                 _v2_obs("o2", BACKFILL, "b", "2026-01", "RY1", 50)]
        self.assertEqual(find_duplicate_source_refs(v2_obs), [])

    def test_detects_two_observation_ids_sharing_one_source_ref(self):
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100),
                 _v2_obs("o2", BACKFILL, "a", "2026-01", "RY1", 100)]
        self.assertEqual(find_duplicate_source_refs(v2_obs), [(BACKFILL, "a")])

    def test_reconciliation_failure_when_units_drift(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100)]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 95)]
        failures = find_reconciliation_failures(legacy, v2_obs)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["legacy_id"], "a")

    def test_no_reconciliation_failure_when_units_match(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100)]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        self.assertEqual(find_reconciliation_failures(legacy, v2_obs), [])


class FullReportTests(unittest.TestCase):
    def test_clean_report_when_everything_agrees(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        v2_facts = [_v2_fact("o1", "acme.gecko", "MODEL", 100)]
        crosswalk = {"uuid-1": "acme.gecko"}
        report = build_parity_report(legacy, v2_obs, v2_facts, crosswalk)
        summary = report.summary()
        self.assertTrue(summary["is_clean"])
        self.assertEqual(summary["pairs_by_classification"], {"agree": 1})

    def test_report_is_not_clean_when_reconciliation_fails(self):
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 90)]
        v2_facts = [_v2_fact("o1", "acme.gecko", "MODEL", 90)]
        crosswalk = {"uuid-1": "acme.gecko"}
        report = build_parity_report(legacy, v2_obs, v2_facts, crosswalk)
        summary = report.summary()
        self.assertFalse(summary["is_clean"])
        self.assertEqual(summary["reconciliation_failures"], 1)

    def test_identity_disagreement_does_not_by_itself_break_volume_parity(self):
        # The packet's key distinction: a mapping disagreement alone must
        # not make the report "unclean" via the volume/duplicate/
        # reconciliation checks - it is visible in pairs_by_classification,
        # not folded into is_clean.
        legacy = [_legacy("a", "2026-01", "RY1", 100, model_id="uuid-1")]
        v2_obs = [_v2_obs("o1", BACKFILL, "a", "2026-01", "RY1", 100)]
        v2_facts = [_v2_fact("o1", "acme.falcon_one", "MODEL", 100)]
        crosswalk = {"uuid-1": "acme.gecko"}
        report = build_parity_report(legacy, v2_obs, v2_facts, crosswalk)
        summary = report.summary()
        self.assertTrue(summary["is_clean"])
        self.assertEqual(summary["pairs_by_classification"],
                         {"identity_disagreement": 1})

    def test_grain_distribution_reported(self):
        legacy = []
        v2_obs = []
        v2_facts = [_v2_fact("o1", "acme.gecko", "MODEL", 10),
                   _v2_fact("o2", "acme.gecko.gen1.lx", "VARIANT", 5),
                   _v2_fact("o3", "acme", "BRAND", 2)]
        report = build_parity_report(legacy, v2_obs, v2_facts, {})
        self.assertEqual(report.grain_distribution,
                         {"MODEL": 10, "VARIANT": 5, "BRAND": 2})


if __name__ == "__main__":
    unittest.main()
