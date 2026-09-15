"""v2 serving rollup: MODEL/VARIANT safe rollup, BRAND never distributed
into models, brand always rolls up safely, no parent/child double count."""

import unittest

from vehreg.registration_v2_rollup import (
    RollupFact,
    brand_component,
    brand_level_rollup,
    model_level_rollup,
    rollup_reconciles,
    unknown_coarse_volume_by_brand,
)


class ComponentTests(unittest.TestCase):
    def test_brand_component_of_a_brand_id_is_itself(self):
        self.assertEqual(brand_component("acme"), "acme")

    def test_brand_component_of_a_model_id(self):
        self.assertEqual(brand_component("acme.gecko"), "acme")

    def test_brand_component_of_a_variant_id(self):
        self.assertEqual(brand_component("acme.gecko.gen1.lx"), "acme")


class ModelLevelRollupTests(unittest.TestCase):
    def test_model_fact_counts_directly(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100)]
        self.assertEqual(model_level_rollup(facts), {"acme.gecko": 100})

    def test_variant_fact_rolls_up_to_its_model(self):
        facts = [RollupFact("acme.gecko.gen1.lx", "VARIANT", 40)]
        self.assertEqual(model_level_rollup(facts), {"acme.gecko": 40})

    def test_model_and_its_own_variant_facts_sum_at_the_model(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("acme.gecko.gen1.lx", "VARIANT", 40)]
        self.assertEqual(model_level_rollup(facts), {"acme.gecko": 140})

    def test_brand_fact_is_excluded_entirely_never_distributed(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("acme", "BRAND", 25)]
        rollup = model_level_rollup(facts)
        self.assertEqual(rollup, {"acme.gecko": 100})
        self.assertNotIn("acme", rollup)
        # The 25 brand-only units are not silently redistributed into
        # acme.gecko or any other model.
        self.assertEqual(rollup["acme.gecko"], 100)


class BrandLevelRollupTests(unittest.TestCase):
    def test_every_grain_rolls_up_safely_to_brand(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("acme.gecko.gen1.lx", "VARIANT", 40),
                RollupFact("acme", "BRAND", 25)]
        self.assertEqual(brand_level_rollup(facts), {"acme": 165})

    def test_two_brands_stay_separate(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("sparkco.watt", "MODEL", 30)]
        self.assertEqual(brand_level_rollup(facts),
                         {"acme": 100, "sparkco": 30})


class UnknownCoarseVolumeTests(unittest.TestCase):
    def test_measurable_and_never_disappears_at_finer_report_grain(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("acme", "BRAND", 25)]
        coarse = unknown_coarse_volume_by_brand(facts)
        self.assertEqual(coarse, {"acme": 25})
        # A model-level report (model_level_rollup) excludes it, but it is
        # not gone - it is measurable right here.
        model_rollup = model_level_rollup(facts)
        self.assertEqual(sum(model_rollup.values()) + sum(coarse.values()),
                         sum(f.units for f in facts))

    def test_empty_when_no_brand_grain_facts_exist(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100)]
        self.assertEqual(unknown_coarse_volume_by_brand(facts), {})


class NoDoubleCountTests(unittest.TestCase):
    def test_reconciles_across_mixed_grains(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("acme.gecko.gen1.lx", "VARIANT", 40),
                RollupFact("acme.falcon_one", "MODEL", 10),
                RollupFact("acme", "BRAND", 25),
                RollupFact("sparkco.watt", "MODEL", 30)]
        self.assertTrue(rollup_reconciles(facts))

    def test_model_plus_coarse_equals_brand_total_exactly(self):
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("acme.gecko.gen1.lx", "VARIANT", 40),
                RollupFact("acme", "BRAND", 25)]
        model_total = sum(model_level_rollup(facts).values())
        coarse_total = sum(unknown_coarse_volume_by_brand(facts).values())
        brand_total = sum(brand_level_rollup(facts).values())
        self.assertEqual(model_total + coarse_total, brand_total)
        self.assertEqual(brand_total, sum(f.units for f in facts))

    def test_empty_fact_set_reconciles_trivially(self):
        self.assertTrue(rollup_reconciles([]))

    def test_a_models_own_variant_is_not_counted_separately_from_the_model_bucket(self):
        # Regression against a naive "sum every fact, then also sum every
        # variant fact again" bug: a variant contributes to its model's
        # bucket exactly once, not to a second, independent variant bucket
        # that would double the model's own total when added back.
        facts = [RollupFact("acme.gecko", "MODEL", 100),
                RollupFact("acme.gecko.gen1.lx", "VARIANT", 40)]
        rollup = model_level_rollup(facts)
        self.assertEqual(len(rollup), 1)
        self.assertEqual(rollup["acme.gecko"], 140)


if __name__ == "__main__":
    unittest.main()
