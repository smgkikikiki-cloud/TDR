from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from automotive.vehicle_master.catalog_maintainer.shadow_snapshot import (
    CONTRACT_VERSION, SOURCE_CONTRACT, ShadowSnapshotError, build_shadow_report,
    normalize_shadow_export, validate_shadow_export, validate_shadow_report,
)

ROOT = Path(__file__).parents[2] / "catalog_maintainer"


def fixture():
    """Small synthetic export in the documented v57 table shape."""
    models = [
        {"canonical_id": "m.current", "generation_id": "g.one", "status": "CURRENT", "payload": {}, "deleted_at": None},
        {"canonical_id": "m.audit", "generation_id": "g.audit", "status": "CURRENT", "payload": {}, "deleted_at": None},
        {"canonical_id": "m.history", "generation_id": "g.history", "status": "HISTORICAL", "payload": {}, "deleted_at": None},
        {"canonical_id": "m.upcoming", "generation_id": "g.upcoming", "status": "UNVERIFIED", "payload": {"upcoming": True}, "deleted_at": None},
        {"canonical_id": "m.deleted", "generation_id": "g.deleted", "status": "CURRENT", "payload": {}, "deleted_at": "2026-01-01"},
    ]
    generations = [
        {"canonical_id": "g.one", "model_id": "m.current", "payload": {}},
        {"canonical_id": "g.two", "model_id": "m.current", "payload": {}},
        {"canonical_id": "g.audit", "model_id": "m.audit", "payload": {}},
        {"canonical_id": "g.history", "model_id": "m.history", "payload": {}},
        {"canonical_id": "g.upcoming", "model_id": "m.upcoming", "payload": {}},
        {"canonical_id": "g.deleted", "model_id": "m.deleted", "payload": {}},
    ]
    trims = [
        {"canonical_id": "t.ice", "model_id": "m.current", "generation_id": "g.one", "name": "ICE", "powertrain": "ICE", "status": "CURRENT", "payload": {}, "catalog_payload": {}},
        {"canonical_id": "t.hev", "model_id": "m.current", "generation_id": "g.one", "name": "HEV", "powertrain": "HEV", "status": "CURRENT", "payload": {}, "catalog_payload": {}},
        {"canonical_id": "t.phev", "model_id": "m.current", "generation_id": "g.two", "name": "PHEV", "powertrain": "PHEV", "status": "CURRENT", "payload": {}, "catalog_payload": {}},
        {"canonical_id": "t.bev", "model_id": "m.current", "generation_id": "g.two", "name": "BEV", "powertrain": "BEV", "status": "CURRENT", "payload": {}, "catalog_payload": {}},
        {"canonical_id": "t.audit", "model_id": "m.audit", "generation_id": "g.audit", "name": "Unknown retail", "powertrain": "HEV", "status": "CURRENT", "payload": {}, "catalog_payload": {}},
        {"canonical_id": "t.old", "model_id": "m.history", "generation_id": "g.history", "name": "Old", "powertrain": "ICE", "status": "HISTORICAL", "payload": {}, "catalog_payload": {}},
        {"canonical_id": "t.future", "model_id": "m.upcoming", "generation_id": "g.upcoming", "name": "Future", "powertrain": "BEV", "status": "CURRENT", "payload": {}, "catalog_payload": {}},
        {"canonical_id": "t.deleted", "model_id": "m.deleted", "generation_id": "g.deleted", "name": "Deleted", "powertrain": "BEV", "status": "CURRENT", "payload": {}, "catalog_payload": {}, "deleted_at": "2026-01-01"},
    ]

    def fact(fid, trim, field, state, value=None, *, verified="VERIFIED", source="fixture", ref="fixture://fact", locked=False, authority="OFFICIAL"):
        return {"fact_id": fid, "trim_id": trim, "field_key": field, "value_state": state, "value": value,
                "unit": "", "qualifiers": {}, "effective_from": None, "effective_to": None, "observed_at": "2026-10-01",
                "claim_ids": [], "verification_status": verified, "source": source, "source_ref": ref,
                "source_locator": "fixture:1", "authority": authority, "locked": locked}

    facts = [
        fact("f.ice.engine", "t.ice", "engine.displacement_cc", "KNOWN", 1498),
        fact("f.ice.battery.na", "t.ice", "battery.catalog_capacity_kwh", "NOT_APPLICABLE"),
        fact("f.ice.length.alias", "t.ice", "length_mm", "KNOWN", 4400),
        fact("f.phev.engine.a", "t.phev", "engine.displacement_cc", "KNOWN", 1498),
        fact("f.phev.engine.b", "t.phev", "engine.displacement_cc", "KNOWN", 1598),
        fact("f.bev.engine.na", "t.bev", "engine.displacement_cc", "NOT_APPLICABLE"),
        fact("f.bev.battery", "t.bev", "battery.catalog_capacity_kwh", "KNOWN", 60.5, ref=""),
        fact("f.bev.seats.lock", "t.bev", "vehicle.seats", "ABSENT", locked=True, authority="ADMIN", ref=""),
        fact("f.ice.seats.duplicate", "t.ice", "vehicle.seats", "KNOWN", 5),
        fact("f.ice.seats.duplicate-copy", "t.ice", "vehicle.seats", "KNOWN", 5),
        fact("f.ice.aeb.provisional", "t.ice", "safety.aeb", "KNOWN", True, verified="PROVISIONAL"),
    ]
    return {
        "contract_version": CONTRACT_VERSION,
        "provenance": {"kind": "SYNTHETIC_FIXTURE", "snapshot_id": "synthetic-shadow-multi-generation-v1",
                       "exported_at": "2026-10-12T00:00:00Z", "anonymized": True,
                       "source_contract": SOURCE_CONTRACT, "source_schema_version": "synthetic-v57-shape"},
        "vehicle_master_state": {"scope": "vehicle_master", "seed_release_id": "synthetic-release",
                                  "seed_as_of": "2026-10-12", "seed_source_hash": "synthetic-only",
                                  "seed_canonical_revision": "synthetic"},
        "field_priority_overlay": {"engine.displacement_cc": "P1", "battery.catalog_capacity_kwh": "P1",
                                   "vehicle.seats": "P1", "vehicle.length_mm": "P1", "safety.aeb": "P2"},
        "evidence_cache": [],
        "tables": {"vehicle_models": models, "vehicle_generations": generations, "vehicle_trims": trims,
                   "vehicle_facts": facts,
                   "vehicle_current_retail_sets": [{"model_id": "m.current", "trim_ids": ["t.ice", "t.hev", "t.phev", "t.bev"],
                       "reviewer": "synthetic-owner", "reviewed_at": "2026-10-01", "source_ref": "fixture://owner-set"}],
                   "vehicle_price_ledger": [{"record_id": "price.1", "trim_id": "t.ice", "amount_thb": 800000,
                       "price_type": "LIST_PRICE", "in_release": True}]},
    }


class ShadowSnapshotTests(unittest.TestCase):
    def policy(self):
        return json.loads((ROOT / "contract" / "policy.yaml").read_text(encoding="utf-8"))

    def test_multi_generation_trim_mapping_and_powertrain_applicability(self):
        snap, meta = normalize_shadow_export(fixture(), repository_root=REPOSITORY_ROOT)
        self.assertEqual({t["generation_id"] for t in snap["trims"] if t["model_id"] == "m.current"}, {"g.one", "g.two"})
        report = build_shadow_report(fixture(), self.policy(), repository_root=REPOSITORY_ROOT)
        by_key = {(r["trim_id"], r["field_key"]): r["state"] for r in report["sample_trace"]}
        self.assertEqual(by_key[("t.ice", "battery.catalog_capacity_kwh")], "NOT_APPLICABLE")
        self.assertEqual(by_key[("t.bev", "engine.displacement_cc")], "NOT_APPLICABLE")
        self.assertEqual(by_key[("t.phev", "battery.catalog_capacity_kwh")], "MISSING")
        self.assertEqual(by_key[("t.hev", "battery.catalog_capacity_kwh")], "MISSING")
        self.assertEqual(by_key[("t.ice", "vehicle.length_mm")], "ALREADY_KNOWN")
        self.assertEqual(meta["production_coverage"], "UNKNOWN")

    def test_current_without_owner_retail_set_is_audit_only_even_with_registration_like_metadata(self):
        source = fixture()
        source["tables"]["vehicle_models"][1]["payload"] = {"registration_count": 99999999}
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(report["coverage"]["models_by_class"]["RETAIL_AUDIT_ONLY"], 1)
        self.assertEqual(report["research"]["retail_audit_jobs"], 1)
        self.assertEqual(report["coverage"]["models_by_class"]["ELIGIBLE_CURRENT"], 1)

    def test_locked_admin_absent_fact_is_not_gap_and_price_ledger_is_separate(self):
        report = build_shadow_report(fixture(), self.policy(), repository_root=REPOSITORY_ROOT)
        states = {(r["trim_id"], r["field_key"]): r["state"] for r in report["sample_trace"]}
        self.assertEqual(states[("t.bev", "vehicle.seats")], "TOMBSTONED_LOCKED")
        self.assertEqual(report["price_ledger"]["spec_gap_inputs"], 0)
        self.assertEqual(report["price_ledger"]["rows_trace_only"], 1)

    def test_conflicting_facts_are_explicit_and_exact_duplicates_are_reported(self):
        report = build_shadow_report(fixture(), self.policy(), repository_root=REPOSITORY_ROOT)
        states = {(r["trim_id"], r["field_key"]): r["state"] for r in report["sample_trace"]}
        self.assertEqual(states[("t.phev", "engine.displacement_cc")], "CONFLICT")
        self.assertEqual(report["gaps"]["duplicate_fact_rows"], 1)
        duplicate = report["duplicate_fact_rows"][0]
        self.assertEqual(duplicate["duplicate_of"], "vehicle_facts:f.ice.seats.duplicate")

    def test_missing_source_provenance_stays_unverified_and_traceable(self):
        report = build_shadow_report(fixture(), self.policy(), repository_root=REPOSITORY_ROOT)
        row = next(r for r in report["sample_trace"] if r["trim_id"] == "t.bev" and r["field_key"] == "battery.catalog_capacity_kwh")
        self.assertEqual(row["state"], "NEEDS_SOURCE_TRACE")
        self.assertIn("vehicle_facts:f.bev.battery", row["fact_record_refs"])
        provisional = next(r for r in report["sample_trace"] if r["trim_id"] == "t.ice" and r["field_key"] == "safety.aeb")
        self.assertEqual(provisional["state"], "NEEDS_SOURCE_TRACE")

    def test_parent_id_conflict_is_held_not_repaired_or_matched(self):
        source = fixture()
        source["tables"]["vehicle_trims"][1]["model_id"] = "m.audit"
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertIn("MODEL_GENERATION_PARENT_MISMATCH", {x["reason"] for x in report["identity_issues"]})
        self.assertNotIn("t.phev", {x["trim_id"] for x in report["gaps"]["items"]})

    def test_wrong_variant_parent_is_an_identity_hold_not_repaired(self):
        source = fixture()
        source["tables"]["vehicle_variants"] = [{"canonical_id": "v.wrong", "generation_id": "g.audit",
            "model_id": "m.audit", "name": "wrong parent", "powertrain": "HEV", "payload": {}}]
        source["tables"]["vehicle_trims"][0]["variant_id"] = "v.wrong"
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        reasons = {item["reason"] for item in report["identity_issues"]}
        self.assertIn("TRIM_VARIANT_PARENT_MISMATCH", reasons)
        self.assertNotIn("t.ice", {item["trim_id"] for item in report["gaps"]["items"]})

    def test_generation_parent_dangling_is_reported_and_removed_from_scope(self):
        source = fixture()
        source["tables"]["vehicle_generations"][0]["model_id"] = "m.unknown"
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        reasons = {item["reason"] for item in report["identity_issues"]}
        self.assertIn("UNKNOWN_MODEL_PARENT", reasons)
        self.assertIn("GENERATION_PARENT_UNRESOLVED", reasons)
        self.assertNotIn("t.ice", {item["trim_id"] for item in report["gaps"]["items"]})

    def test_status_classification_keeps_historical_upcoming_and_deleted_out(self):
        report = build_shadow_report(fixture(), self.policy(), repository_root=REPOSITORY_ROOT)
        classes = report["coverage"]["models_by_class"]
        self.assertEqual(classes["HISTORICAL"], 1)
        self.assertEqual(classes["UPCOMING"], 1)
        self.assertEqual(classes["DELETED"], 1)
        self.assertEqual(report["coverage"]["trims_by_class"]["RETIRED_OR_HISTORICAL"], 1)
        trim_classes = {r["canonical_id"]: r["classification"] for r in report["classification_trace"] if r["entity_type"] == "TRIM"}
        self.assertEqual(trim_classes["t.future"], "UPCOMING")
        self.assertEqual(trim_classes["t.deleted"], "DELETED")
        self.assertEqual(trim_classes["t.old"], "RETIRED_OR_HISTORICAL")

    def test_historical_trim_inside_current_model_is_never_spec_enriched(self):
        source = fixture()
        source["tables"]["vehicle_trim_lifecycle_decisions"] = [{
            "trim_id": "t.phev", "status": "HISTORICAL", "reviewer": "synthetic-owner",
            "reviewed_at": "2026-10-02", "source_ref": "fixture://lifecycle"}]
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(report["research"]["spec_enrich_jobs"], 1)
        self.assertEqual(report["coverage"]["trims_by_class"]["RETIRED_OR_HISTORICAL"], 2)
        self.assertNotIn("t.phev", {row["trim_id"] for row in report["sample_trace"]})
        trace = next(r for r in report["classification_trace"] if r["canonical_id"] == "t.phev")
        self.assertIn("vehicle_trim_lifecycle_decisions:t.phev", trace["input_record_refs"])

    def test_schema_version_top_level_and_unknown_row_columns_fail_closed(self):
        source = fixture()
        source["contract_version"] = "vehicle-master-shadow/999"
        with self.assertRaises(ShadowSnapshotError):
            validate_shadow_export(source)
        source = fixture()
        source["tables"]["vehicle_models"][0]["future_unknown_column"] = "ignored?"
        with self.assertRaises(ShadowSnapshotError):
            validate_shadow_export(source)

    def test_repeat_report_is_byte_stable(self):
        first = build_shadow_report(fixture(), self.policy(), repository_root=REPOSITORY_ROOT)
        second = build_shadow_report(copy.deepcopy(fixture()), self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(json.dumps(first, sort_keys=True, separators=(",", ":")),
                         json.dumps(second, sort_keys=True, separators=(",", ":")))
        self.assertEqual(first["activity"], {"external_http_calls": 0, "paid_ai_calls": 0, "paid_search_calls": 0,
                         "paid_tokens": 0, "paid_spend_thb": 0, "production_database_accesses": 0,
                         "canonical_writes": 0, "background_workers": 0})

    def test_output_contract_rejects_unresolved_trace_and_nonzero_activity(self):
        report = build_shadow_report(fixture(), self.policy(), repository_root=REPOSITORY_ROOT)
        bad_trace = copy.deepcopy(report)
        bad_trace["sample_trace"][0]["trim_record_ref"] = "vehicle_trims:not-in-input"
        with self.assertRaises(ShadowSnapshotError):
            validate_shadow_report(bad_trace)
        bad_activity = copy.deepcopy(report)
        bad_activity["activity"]["canonical_writes"] = 1
        with self.assertRaises(ShadowSnapshotError):
            validate_shadow_report(bad_activity)

    def test_table_fetch_order_does_not_change_hash_report_or_duplicate_resolution(self):
        source = fixture()
        reversed_source = copy.deepcopy(source)
        for rows in reversed_source["tables"].values():
            rows.reverse()
        first = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        second = build_shadow_report(reversed_source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(first, second)

    def test_unverified_model_metadata_cannot_unlock_spec_enrichment(self):
        source = fixture()
        source["tables"]["vehicle_models"][1]["payload"] = {
            "lineup_evidence": {"market": "TH", "source_authority": "OFFICIAL", "completeness": "COMPLETE_LINEUP"},
            "registration_count": 5000000,
        }
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(report["research"]["spec_enrich_jobs"], 1)  # only m.current has owner-set authority
        self.assertEqual(report["research"]["retail_audit_jobs"], 1)
        self.assertEqual(report["coverage"]["models_by_class"]["RETAIL_AUDIT_ONLY"], 1)

    def complete_lineup_document(self, model_id, generation_id, trim_id):
        doc = json.loads((ROOT / "fixtures" / "recorded_docs" / "complete-lineup.json").read_text(encoding="utf-8"))
        content = doc["content"].replace("byd.atto_3", model_id).replace("atto_3.g1", generation_id).replace("atto.extended", trim_id)
        content = "\n".join(line for line in content.splitlines() if "atto.standard" not in line)
        doc.update(document_id=f"doc-{model_id}", model_id=model_id, generation_id=generation_id,
                   trim_ids=[trim_id], content=content)
        doc["content_sha256"] = __import__("hashlib").sha256(content.encode()).hexdigest()
        doc["capture_manifest"].update(listed_trim_ids=[trim_id], row_count=1)
        doc["completeness_evidence"]["quote"] = next(line for line in content.splitlines() if line.startswith("lineup_attestation|"))
        doc["completeness_evidence"]["locator"] = f"line:{next(i for i,line in enumerate(content.splitlines(),1) if line.startswith('lineup_attestation|'))}"
        doc["lineup_rows"] = [{"market_trim_id": trim_id, "model_id": model_id, "generation_id": generation_id,
                               "grade": None, "powertrain": "HEV", "model_year": None, "facelift_id": None}]
        doc["local_source_id"] = f"fixture://{doc['document_id']}"
        return doc

    def test_valid_complete_source_document_can_establish_only_its_unambiguous_model_lineup(self):
        source = fixture()
        source["evidence_cache"] = [self.complete_lineup_document("m.audit", "g.audit", "t.audit")]
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(report["coverage"]["models_by_class"]["ELIGIBLE_CURRENT"], 2)
        trace = next(r for r in report["classification_trace"] if r["entity_type"] == "MODEL" and r["canonical_id"] == "m.audit")
        self.assertIn("evidence_cache:doc-m.audit", trace["input_record_refs"])

    def test_one_generation_document_cannot_unlock_multi_generation_model(self):
        source = fixture()
        source["tables"]["vehicle_current_retail_sets"] = []
        source["evidence_cache"] = [self.complete_lineup_document("m.current", "g.one", "t.ice")]
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(report["coverage"]["models_by_class"]["RETAIL_AUDIT_ONLY"], 2)
        self.assertEqual(report["research"]["spec_enrich_jobs"], 0)

    def test_corrupt_cached_document_hash_is_explicitly_held(self):
        source = fixture()
        doc = self.complete_lineup_document("m.audit", "g.audit", "t.audit")
        doc["content_sha256"] = "0" * 64
        source["evidence_cache"] = [doc]
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(report["coverage"]["models_by_class"]["RETAIL_AUDIT_ONLY"], 1)
        self.assertEqual(report["evidence_issues"][0]["reason"], "SOURCE_DOCUMENT_INVALID")

    def test_partial_lineup_evidence_does_not_establish_current_membership(self):
        source = fixture()
        doc = self.complete_lineup_document("m.audit", "g.audit", "t.audit")
        doc["completeness"] = "PARTIAL_TRIM_LIST"
        doc["capture_manifest"]["pagination_complete"] = False
        source["evidence_cache"] = [doc]
        report = build_shadow_report(source, self.policy(), repository_root=REPOSITORY_ROOT)
        self.assertEqual(report["coverage"]["models_by_class"]["RETAIL_AUDIT_ONLY"], 1)
        self.assertEqual(report["research"]["spec_enrich_jobs"], 1)
        self.assertEqual(report["research"]["retail_audit_jobs"], 1)

    def test_non_synthetic_provenance_requires_anonymization_and_pin(self):
        source = fixture()
        source["provenance"].update(kind="AUTHORIZED_LOCAL_EXPORT", anonymized=False, source_schema_version="v57-v61")
        with self.assertRaises(ShadowSnapshotError):
            validate_shadow_export(source)


if __name__ == "__main__":
    unittest.main()
