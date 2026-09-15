"""registration_v2_writer.build_batch: reconciliation, no double-counting,
determinism, and unresolved-visibility guarantees."""

import unittest

from tests.test_resolution_v2 import _catalog, _obs, _resolver
from vehreg.registration_v2_writer import build_batch


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.resolver = _resolver(self.catalog)

    def test_source_units_reconcile_exactly(self):
        observations = [
            _obs("Acme", "Gecko", reg="RY1"),           # resolves MODEL
            _obs("Acme", "Zzzznope", reg="RY1"),          # resolves BRAND
            _obs("Nonexistent Motors", "Whatever", reg="RY1"),  # unresolved
        ]
        batch = build_batch(observations, self.resolver, self.catalog,
                            now="2026-09-15T00:00:00Z")
        self.assertTrue(batch.reconciles())
        self.assertEqual(batch.total_units,
                         sum(o.units for o in observations))
        self.assertEqual(batch.resolved_units + batch.unresolved_units,
                         batch.total_units)

    def test_unresolved_units_remain_visible(self):
        unresolved = _obs("Nonexistent Motors", "Whatever", reg="RY1")
        batch = build_batch([unresolved], self.resolver, self.catalog)
        self.assertEqual(batch.fact_rows, [])
        self.assertEqual(len(batch.observation_rows), 1)
        self.assertEqual(batch.unresolved_units, unresolved.units)
        self.assertEqual(len(batch.review_rows), 1)
        self.assertEqual(batch.review_rows[0]["best_canonical_id"], None)

    def test_no_double_counting_between_fact_and_unresolved(self):
        observations = [_obs("Acme", "Gecko", reg="RY1"),
                       _obs("Nonexistent Motors", "X", reg="RY1")]
        batch = build_batch(observations, self.resolver, self.catalog)
        resolved_ids = {r["observation_id"] for r in batch.fact_rows}
        unresolved_ids = {r.observation.observation_id for r in batch.resolutions
                          if r.fact_row is None}
        self.assertEqual(resolved_ids & unresolved_ids, set())
        self.assertEqual(resolved_ids | unresolved_ids,
                         {o.observation_id for o in observations})

    def test_repeated_observation_does_not_double_count(self):
        obs = _obs("Acme", "Gecko", reg="RY1")
        batch = build_batch([obs, obs, obs], self.resolver, self.catalog)
        self.assertEqual(len(batch.observation_rows), 1)
        self.assertEqual(len(batch.fact_rows), 1)
        self.assertEqual(batch.resolved_units, obs.units)

    def test_deterministic_output(self):
        observations = [_obs("Acme", "Gecko", reg="RY1"),
                       _obs("Acme", "Ranger", reg="RY1"),
                       _obs("Acme", "Falcon X", reg="RY1")]
        first = build_batch(observations, self.resolver, self.catalog,
                            now="2026-09-15T00:00:00Z")
        second = build_batch(observations, self.resolver, self.catalog,
                             now="2026-09-15T00:00:00Z")
        self.assertEqual(first.observation_rows, second.observation_rows)
        self.assertEqual(first.fact_rows, second.fact_rows)
        self.assertEqual(first.review_rows, second.review_rows)

    def test_model_ambiguity_produces_a_brand_grain_fact_and_a_review_row(self):
        batch = build_batch([_obs("Acme", "Falcon X", reg="RY1")],
                           self.resolver, self.catalog)
        self.assertEqual(len(batch.fact_rows), 1)
        self.assertEqual(batch.fact_rows[0]["grain"], "BRAND")
        self.assertEqual(len(batch.review_rows), 1)
        self.assertTrue(batch.review_rows[0]["reason"].startswith(
            "model-ambiguous"))
        self.assertEqual(sorted(batch.review_rows[0]["candidates"]),
                         ["acme.falcon_one", "acme.falcon_two"])

    def test_trim_detail_is_attached_only_to_model_grain_trim_detail_facts(self):
        batch = build_batch([_obs("SparkCo", "WATT (300KM-PRO)", reg="RY1")],
                           self.resolver, self.catalog)
        self.assertEqual(len(batch.fact_rows), 1)
        fact = batch.fact_rows[0]
        self.assertEqual(fact["grain"], "MODEL")
        self.assertIsNotNone(fact["trim_detail"])
        self.assertEqual(fact["trim_detail"]["grade"], "PRO")

        plain = build_batch([_obs("Acme", "Gecko", reg="RY1")],
                           self.resolver, self.catalog)
        self.assertIsNone(plain.fact_rows[0]["trim_detail"])

    def test_summary_is_internally_consistent(self):
        observations = [_obs("Acme", "Gecko", reg="RY1"),
                       _obs("Acme", "Zzzznope", reg="RY1"),
                       _obs("Nonexistent Motors", "X", reg="RY1")]
        batch = build_batch(observations, self.resolver, self.catalog)
        summary = batch.summary()
        self.assertEqual(summary["observations"], 3)
        self.assertEqual(summary["facts"], 2)
        self.assertTrue(summary["reconciles"])
        self.assertEqual(summary["facts_by_grain"].get("MODEL"), 1)
        self.assertEqual(summary["facts_by_grain"].get("BRAND"), 1)


if __name__ == "__main__":
    unittest.main()
