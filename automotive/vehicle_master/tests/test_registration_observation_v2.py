"""RegistrationObservation adapters: shape, determinism, reconciliation."""

import unittest

from vehreg.ingest import ColumnMap
from vehreg.registration_observation import (
    DLT_CKAN,
    DLT_CSV,
    LEGACY_REGISTRATIONS_BACKFILL,
    from_dlt_record,
    from_legacy_registration_row,
    from_mapped_row,
    observation_id,
    reconciles,
)


class DeterministicKeyTests(unittest.TestCase):
    def test_observation_id_is_a_pure_function_of_source_identity(self):
        first = observation_id(DLT_CKAN, "resource-1:42")
        second = observation_id(DLT_CKAN, "resource-1:42")
        self.assertEqual(first, second)

    def test_different_source_ref_gives_different_id(self):
        self.assertNotEqual(observation_id(DLT_CKAN, "resource-1:42"),
                            observation_id(DLT_CKAN, "resource-1:43"))

    def test_different_source_kind_gives_different_id_for_the_same_ref(self):
        self.assertNotEqual(observation_id(DLT_CKAN, "x"),
                            observation_id(DLT_CSV, "x"))


class DltCkanAdapterTests(unittest.TestCase):
    def test_adapts_a_ckan_record(self):
        record = {"_id": 7, "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV",
                 "จำนวน": "4,213", "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน"}
        obs = from_dlt_record(record, resource_id="res-9", period="2026-01",
                              registration_type="RY1")
        self.assertEqual(obs.source_kind, DLT_CKAN)
        self.assertEqual(obs.source_ref, "res-9:7")
        self.assertEqual(obs.units, 4213.0)
        self.assertEqual(obs.raw_brand, "TOYOTA")
        self.assertEqual(obs.raw_model, "YARIS ATIV")
        self.assertEqual(obs.province, "ALL")
        self.assertEqual(obs.source_metadata["resource_id"], "res-9")
        self.assertEqual(obs.source_metadata["ckan_record_id"], 7)

    def test_reruns_produce_the_same_observation_id(self):
        record = {"_id": 7, "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV",
                 "จำนวน": "4213", "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน"}
        a = from_dlt_record(record, resource_id="res-9", period="2026-01",
                            registration_type="RY1")
        b = from_dlt_record(dict(record), resource_id="res-9", period="2026-01",
                            registration_type="RY1")
        self.assertEqual(a.observation_id, b.observation_id)
        self.assertEqual(a.payload_hash, b.payload_hash)


class MappedRowAdapterTests(unittest.TestCase):
    def test_adapts_a_mapped_csv_row(self):
        colmap = ColumnMap(period="เดือน", brand="ยี่ห้อ", model="แบบรถ",
                          units="จำนวน", registration_type="ประเภท")
        row = {"เดือน": "2026-02", "ยี่ห้อ": "BYD", "แบบรถ": "ATTO3",
              "จำนวน": "150", "ประเภท": "RY1"}
        obs = from_mapped_row(row, colmap, file_sha256="abc123", row_index=3)
        self.assertIsNotNone(obs)
        self.assertEqual(obs.source_kind, DLT_CSV)
        self.assertEqual(obs.source_ref, "abc123:3")
        self.assertEqual(obs.period, "2026-02")
        self.assertEqual(obs.units, 150.0)
        self.assertEqual(obs.registration_type, "RY1")

    def test_unreadable_units_yields_no_observation(self):
        colmap = ColumnMap(period="p", brand="b", model="m", units="u")
        row = {"p": "2026-02", "b": "BYD", "m": "ATTO3", "u": "n/a"}
        self.assertIsNone(from_mapped_row(row, colmap, file_sha256="x",
                                         row_index=0))

    def test_unreadable_period_yields_no_observation(self):
        colmap = ColumnMap(period="p", brand="b", model="m", units="u")
        row = {"p": "not-a-period", "b": "BYD", "m": "ATTO3", "u": "10"}
        self.assertIsNone(from_mapped_row(row, colmap, file_sha256="x",
                                         row_index=0))

    def test_two_different_rows_in_the_same_file_get_different_ids(self):
        colmap = ColumnMap(period="p", brand="b", model="m", units="u")
        first = from_mapped_row({"p": "2026-02", "b": "A", "m": "X", "u": "1"},
                                colmap, file_sha256="f", row_index=0)
        second = from_mapped_row({"p": "2026-02", "b": "A", "m": "X", "u": "1"},
                                 colmap, file_sha256="f", row_index=1)
        self.assertNotEqual(first.observation_id, second.observation_id)


class LegacyRegistrationRowAdapterTests(unittest.TestCase):
    def test_adapts_a_legacy_registrations_row(self):
        row = {"id": "11111111-1111-4111-8111-111111111111",
              "period": "2026-01-01", "registration_type": "RY1",
              "brand_name_raw": "TOYOTA", "model_name_raw": "YARIS ATIV",
              "model_id": "22222222-2222-4222-8222-222222222222",
              "registrations": 4213, "source_id": "33333333-3333-4333-8333-333333333333",
              "mapping_method": "reviewed-alias"}
        obs = from_legacy_registration_row(row)
        self.assertEqual(obs.source_kind, LEGACY_REGISTRATIONS_BACKFILL)
        self.assertEqual(obs.source_ref, row["id"])
        self.assertEqual(obs.period, "2026-01")
        self.assertEqual(obs.units, 4213.0)
        self.assertEqual(obs.province, "ALL")
        self.assertEqual(obs.raw_variant, "")
        # Legacy UUID/mapping_method are parity evidence only, carried as
        # metadata - never promoted into a resolution-input field.
        self.assertEqual(obs.source_metadata["legacy_model_id"], row["model_id"])
        self.assertEqual(obs.source_metadata["legacy_mapping_method"],
                         "reviewed-alias")

    def test_does_not_repair_a_null_legacy_model_id(self):
        row = {"id": "11111111-1111-4111-8111-111111111111",
              "period": "2026-01-01", "registration_type": "RY1",
              "brand_name_raw": "SOMEBRAND", "model_name_raw": "SOMEMODEL",
              "model_id": None, "registrations": 5, "source_id": None,
              "mapping_method": "unmapped"}
        obs = from_legacy_registration_row(row)
        self.assertIsNone(obs.source_metadata["legacy_model_id"])

    def test_reruns_over_the_same_row_are_idempotent(self):
        row = {"id": "11111111-1111-4111-8111-111111111111",
              "period": "2026-01-01", "registration_type": "RY1",
              "brand_name_raw": "TOYOTA", "model_name_raw": "YARIS ATIV",
              "model_id": None, "registrations": 4213, "source_id": None,
              "mapping_method": "unmapped"}
        a = from_legacy_registration_row(row)
        b = from_legacy_registration_row(dict(row))
        self.assertEqual(a.observation_id, b.observation_id)


class ReconciliationTests(unittest.TestCase):
    def test_reconciles_when_units_sum_matches(self):
        colmap = ColumnMap(period="p", brand="b", model="m", units="u")
        rows = [from_mapped_row({"p": "2026-02", "b": "A", "m": "X", "u": str(n)},
                                colmap, file_sha256="f", row_index=i)
               for i, n in enumerate((10, 20, 30))]
        self.assertTrue(reconciles(rows, expected_total=60))

    def test_does_not_reconcile_when_units_sum_disagrees(self):
        colmap = ColumnMap(period="p", brand="b", model="m", units="u")
        rows = [from_mapped_row({"p": "2026-02", "b": "A", "m": "X", "u": "10"},
                                colmap, file_sha256="f", row_index=0)]
        self.assertFalse(reconciles(rows, expected_total=99))


if __name__ == "__main__":
    unittest.main()
