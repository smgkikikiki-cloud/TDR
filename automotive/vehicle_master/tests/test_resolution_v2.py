"""DLT v2 resolution semantics: observation -> deepest grain the evidence proves.

Uses a small synthetic catalog (mirroring ``tests.test_vehreg.tiny_payload``'s
own pattern) built specifically to exercise every stopping point Resolver
supports: exact match, ambiguity, brand-only, fully unresolved, RY-class
tie-breaking, variant residual, and a trim-detail brand.
"""

import itertools
import unittest

from vehreg import db
from vehreg.catalog import DEFAULT_YEAR, Catalog
from vehreg.ingest import ColumnMap, Resolver
from vehreg.registration_observation import from_mapped_row
from vehreg.resolution_v2 import derive_trim_detail, resolve_observation
from vehreg.taxonomy import Grain

YEAR = DEFAULT_YEAR


def _payload():
    return {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": "แอคมี่",
                  "brand_segment": "MASS"},
        "models": [
            {"id": "gecko", "name_en": "Gecko", "name_th": "เกคโค่",
             "body_type": "CROSSOVER",
             "generations": [{"code": "G1", "variants": [
                 {"name": "1.5 Base", "powertrain": "ICE", "engine_cc": 1500}]}]},
            {"id": "falcon_one", "name_en": "Falcon One", "name_th": "ฟอลคอนวัน",
             "body_type": "CROSSOVER", "aliases": ["Falcon X"],
             "generations": [{"code": "G1", "variants": [
                 {"name": "1.5", "powertrain": "ICE", "engine_cc": 1500}]}]},
            {"id": "falcon_two", "name_en": "Falcon Two", "name_th": "ฟอลคอนทู",
             "body_type": "CROSSOVER", "aliases": ["Falcon X"],
             "generations": [{"code": "G1", "variants": [
                 {"name": "1.5", "powertrain": "ICE", "engine_cc": 1500}]}]},
            {"id": "ranger_single_smart", "name_en": "Ranger Single Smart",
             "nameplate": "Ranger", "body_type": "PICKUP",
             "cab_type": "SINGLE_SMART", "aliases": ["Ranger"],
             "generations": [{"code": "G1", "variants": [
                 {"name": "2.2 Base", "powertrain": "ICE", "engine_cc": 2200}]}]},
            {"id": "ranger_double_cab", "name_en": "Ranger Double Cab",
             "nameplate": "Ranger", "body_type": "PICKUP",
             "cab_type": "DOUBLE_CAB", "aliases": ["Ranger"],
             "generations": [{"code": "G1", "variants": [
                 {"name": "2.2 4x4", "powertrain": "ICE", "engine_cc": 2200}]}]},
            {"id": "comet", "name_en": "Comet", "name_th": "โคเมท",
             "body_type": "CROSSOVER",
             "generations": [{"code": "G1", "variants": [
                 {"name": "Comet Base", "powertrain": "ICE", "engine_cc": 1500},
                 {"name": "Comet GT", "powertrain": "ICE", "engine_cc": 1800,
                  "aliases": ["GT"]},
             ]}]},
        ],
    }


def _sparkco_payload():
    return {
        "brand": {"id": "sparkco", "name_en": "SparkCo", "name_th": "สปาร์คโค",
                  "brand_segment": "MASS", "trim_detail": True},
        "models": [
            {"id": "watt", "name_en": "Watt", "name_th": "วัตต์",
             "body_type": "CROSSOVER",
             "generations": [{"code": "G1", "variants": [
                 {"name": "Watt Long Range", "powertrain": "BEV",
                  "battery_kwh": 60.0}]}]},
        ],
    }


def _catalog() -> Catalog:
    catalog = Catalog(YEAR)
    catalog.add_brand_payload(_payload(), source="<test>")
    catalog.add_brand_payload(_sparkco_payload(), source="<test>")
    catalog.build_indexes()
    return catalog


def _resolver(catalog: Catalog) -> Resolver:
    conn = db.connect(":memory:")
    return Resolver(catalog, conn)


_obs_counter = itertools.count()


def _obs(raw_brand: str, raw_model: str, *, reg: str = "RY1",
        raw_variant: str = "", units: str = "1"):
    row = {"brand": raw_brand, "model": raw_model, "variant": raw_variant,
          "units": units, "period": "2026-01", "reg": reg}
    colmap = ColumnMap(brand="brand", model="model", variant="variant",
                      units="units", period="period", registration_type="reg")
    # Each call gets its own row_index, so distinct calls (even with
    # identical raw content) get distinct, but still deterministic,
    # observation ids - the same rule a real distinct source row would
    # satisfy. Tests that specifically want the *same* observation twice
    # build one observation object and reuse it, rather than calling _obs
    # twice with the same arguments.
    observation = from_mapped_row(row, colmap, file_sha256="deadbeef",
                                  row_index=next(_obs_counter))
    assert observation is not None
    return observation


class ResolutionSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.resolver = _resolver(self.catalog)

    def test_exact_model_match(self):
        result = resolve_observation(
            self.resolver, _obs("Acme", "Gecko", reg="RY1"))
        self.assertEqual(result.canonical_id, "acme.gecko")
        self.assertIs(result.grain, Grain.MODEL)
        self.assertEqual(result.reason, "")
        self.assertTrue(result.is_resolved)
        self.assertFalse(result.stopped_short)

    def test_model_ambiguity_stays_coarse(self):
        result = resolve_observation(
            self.resolver, _obs("Acme", "Falcon X", reg="RY1"))
        self.assertEqual(result.canonical_id, "acme")     # brand grain only
        self.assertIs(result.grain, Grain.BRAND)
        self.assertTrue(result.reason.startswith("model-ambiguous"))
        self.assertTrue(result.is_resolved)
        self.assertTrue(result.stopped_short)
        self.assertEqual(set(result.candidates),
                         {"acme.falcon_one", "acme.falcon_two"})

    def test_brand_only_resolution(self):
        result = resolve_observation(
            self.resolver, _obs("Acme", "Zzzznope", reg="RY1"))
        self.assertEqual(result.canonical_id, "acme")
        self.assertIs(result.grain, Grain.BRAND)
        self.assertEqual(result.reason, "model-not-found")
        self.assertTrue(result.is_resolved)

    def test_completely_unresolved_observation(self):
        result = resolve_observation(
            self.resolver, _obs("Nonexistent Motors", "Whatever", reg="RY1"))
        self.assertIsNone(result.canonical_id)
        self.assertIsNone(result.grain)
        self.assertEqual(result.reason, "brand-not-found")
        self.assertFalse(result.is_resolved)
        self.assertTrue(result.stopped_short)

    def test_ry_class_tie_breaking(self):
        double_cab = resolve_observation(
            self.resolver, _obs("Acme", "Ranger", reg="RY1"))
        single_smart = resolve_observation(
            self.resolver, _obs("Acme", "Ranger", reg="RY3"))
        self.assertEqual(double_cab.canonical_id, "acme.ranger_double_cab")
        self.assertEqual(single_smart.canonical_id, "acme.ranger_single_smart")
        self.assertIs(double_cab.grain, Grain.MODEL)
        self.assertIs(single_smart.grain, Grain.MODEL)
        self.assertEqual(double_cab.reason, "")
        self.assertEqual(single_smart.reason, "")

    def test_same_raw_label_different_registration_types_resolve_differently(self):
        # The exact same assertion as the RY tie-break test, stated as its
        # own scenario per the packet's required-coverage list: one raw
        # label, two DLT classes, two different canonical targets.
        a = resolve_observation(self.resolver, _obs("Acme", "Ranger", reg="RY1"))
        b = resolve_observation(self.resolver, _obs("Acme", "Ranger", reg="RY3"))
        self.assertNotEqual(a.canonical_id, b.canonical_id)

    def test_variant_only_with_sufficient_residual_detail(self):
        with_residual = resolve_observation(
            self.resolver, _obs("Acme", "Comet GT", reg="RY1"))
        self.assertEqual(with_residual.canonical_id, "acme.comet.g1.comet_gt")
        self.assertIs(with_residual.grain, Grain.VARIANT)
        self.assertEqual(with_residual.reason, "")

    def test_no_variant_claimed_without_residual_detail(self):
        bare = resolve_observation(
            self.resolver, _obs("Acme", "Comet", reg="RY1"))
        self.assertEqual(bare.canonical_id, "acme.comet")
        self.assertIs(bare.grain, Grain.MODEL)
        self.assertEqual(bare.reason, "")

    def test_trim_detail_marque_remains_model_grain(self):
        result = resolve_observation(
            self.resolver, _obs("SparkCo", "WATT (300KM-PRO)", reg="RY1"))
        self.assertEqual(result.canonical_id, "sparkco.watt")
        self.assertIs(result.grain, Grain.MODEL)
        self.assertEqual(result.reason, "")

    def test_no_markettrim_output(self):
        """Grain is always BRAND/MODEL/VARIANT - MarketTrim is not a member
        of the Grain vocabulary at all, so this resolver structurally cannot
        produce trim-level retail identity. See Invariant 7."""
        for obs in (_obs("Acme", "Gecko", reg="RY1"),
                   _obs("Acme", "Comet GT", reg="RY1"),
                   _obs("SparkCo", "WATT (300KM-PRO)", reg="RY1")):
            result = resolve_observation(self.resolver, obs)
            self.assertIn(result.grain, (Grain.BRAND, Grain.MODEL, Grain.VARIANT))
            self.assertNotIn(result.canonical_id, self.catalog.trims)

    def test_deterministic_output(self):
        obs = _obs("Acme", "Ranger", reg="RY1")
        first = resolve_observation(self.resolver, obs)
        second = resolve_observation(self.resolver, obs)
        self.assertEqual(first, second)


class TrimDetailDerivationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.resolver = _resolver(self.catalog)

    def test_trim_detail_derived_for_trim_detail_brand(self):
        obs = _obs("SparkCo", "WATT (300KM-PRO)", reg="RY1")
        result = resolve_observation(self.resolver, obs)
        detail = derive_trim_detail(self.catalog, result, obs.raw_label)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["grade"], "PRO")
        self.assertEqual(detail["range_km"], 300.0)

    def test_no_trim_detail_for_non_trim_detail_brand(self):
        obs = _obs("Acme", "Gecko", reg="RY1")
        result = resolve_observation(self.resolver, obs)
        detail = derive_trim_detail(self.catalog, result, obs.raw_label)
        self.assertIsNone(detail)

    def test_no_trim_detail_when_grain_is_not_model(self):
        # Brand-only and variant-grain resolutions never carry a MODEL-grain
        # trim-detail payload, even for a trim-detail brand.
        obs = _obs("SparkCo", "Zzzznope", reg="RY1")
        result = resolve_observation(self.resolver, obs)
        self.assertIs(result.grain, Grain.BRAND)
        self.assertIsNone(derive_trim_detail(self.catalog, result, obs.raw_label))


if __name__ == "__main__":
    unittest.main()
