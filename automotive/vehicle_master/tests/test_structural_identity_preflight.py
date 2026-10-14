import hashlib
import json
from pathlib import Path

from tools.structural_identity_preflight import prepare, ROOT, CATALOG, FROZEN_SOURCE_SHA256


def test_frozen_nine_identity_preflight_reconciles_genuine_m7_and_owner_ledger(tmp_path):
    catalog_hash = hashlib.sha256(CATALOG.read_bytes()).hexdigest()
    result = prepare(tmp_path / "inputs.json")
    assert len(result["candidates"]) == 9
    assert sum(c["registrations"] for c in result["candidates"]) == 59_948
    assert result["source_reconciliation"] == {
        "source_scopes": 1407, "source_registrations": 4_141_987,
        "effective_registrations": 4_123_704, "excluded_registrations": 18_283,
        "exact_class_scope_and_units_equal_m7_zip": True,
    }
    assert result["frozen_owner_decisions"]["total"] == 244
    assert result["frozen_owner_decisions"]["changed"] == 0
    assert result["frozen_owner_decisions"]["mismatches"] == 0
    assert result["source_files_sha256"] == FROZEN_SOURCE_SHA256
    assert hashlib.sha256(CATALOG.read_bytes()).hexdigest() == catalog_hash


def test_stored_real_preflight_holds_raptor_alias_without_reopening_owner_target():
    report = json.loads((ROOT / "docs/vehicle-db/structural-writer/nine_identity_preflight_report.json").read_text())
    assert report["counts"] == {
        "requested_identities": 9, "requested_registrations": 59948,
        "valid_basic_identity_proposals": 8, "valid_proposal_registrations": 47109,
        "review_hold_identities": 1, "review_hold_registrations": 12839,
    }
    catalog = json.loads(CATALOG.read_text())
    model = next(r for r in catalog["relations"]["vehicle_models"]["rows"] if r["canonical_id"] == "ford.ranger_double_cab")
    assert "ranger raptor" in model["aliases"]
    repair = report["held_catalog_repair_candidates"][0]
    assert repair["canonical_id"] == "ford.ranger_raptor_double_cab"
    assert repair["owner_target_unchanged"]
    assert all(c["canonical_segment"] == "UNKNOWN" and c["canonical_body_type"] == "UNKNOWN" for c in report["candidates"])
    assert report["production"]["newly_approved_or_servable_registrations"] == 0
    assert report["offline_transaction_simulation"]["r6_denied_with_zero_link_changes"]


def test_existing_schema_gaps_are_reported_without_fabricated_db_compatibility():
    schema = (ROOT / "supabase/migration_v57_vehicle_master_tables.sql").read_text()
    rules = (ROOT / "supabase/migration_v59_vehicle_engine_rules.sql").read_text()
    price = (ROOT / "supabase/migration_v66_vehicle_master_governed_writer.sql").read_text()
    legacy = (ROOT / "supabase/migration_v63_ice_model_crosswalk.sql").read_text()
    contract = (ROOT / "docs/vehicle-db/STRUCTURAL_IDENTITY_WRITER_DB_CONTRACT.md").read_text()
    assert "seed_release_id text not null" in schema
    assert "model_has_generation" in rules and "model_has_variant" in rules
    assert "unknown body_type" in rules and "vm_rule_structure" in rules
    assert "('LIST_PRICE', 'CAMPAIGN_PRICE', 'TRIM_LISTING')" in price
    table = legacy.split("create table if not exists public.ice_model_crosswalk (")[1].split(");", 1)[0]
    assert "reg_type_scope" not in table
    for marker in ["BASIC", "C02", "C01", "vm_observations", "canonical_write_revisions", "SERIALIZABLE", "R6"]:
        assert marker in contract
    server = (ROOT / "lib/vehicle-engine/structural-writer-server.ts").read_text()
    assert 'import "server-only"' in server and "currentStructuralAdmin" in server
    assert "actor_id: editor.principal_id" in server and "r6_allowed: false" in server
