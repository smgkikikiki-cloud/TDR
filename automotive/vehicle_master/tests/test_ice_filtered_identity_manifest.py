import csv
import hashlib
import json
from pathlib import Path

from tools.ice_filtered_identity_manifest import (
    M7_ZIP,
    PACKAGE,
    below_registration_threshold,
    coalesce_candidate_targets,
    find_duplicate_candidate_names,
    lifecycle,
    write_manifest,
)


ROOT = Path(__file__).resolve().parents[3]
CATALOG = PACKAGE / "qa/vehicle_master_identity_snapshot_2026-10-13.json"


def test_39_40_registration_boundary_is_group_total_inclusive():
    assert below_registration_threshold(39)
    assert not below_registration_threshold(40)
    assert not below_registration_threshold(20 + 20)


def test_multiple_ice_groups_can_share_one_canonical_identity():
    rows = [
        {"model_group_id": "ice-a", "canonical_model_id": "toyota.camry", "brand": "Toyota", "canonical_name_en": "Camry"},
        {"model_group_id": "ice-b", "canonical_model_id": "toyota.camry", "brand": "TOYOTA", "canonical_name_en": "Camry"},
    ]
    groups, conflicts = coalesce_candidate_targets(rows)
    assert not conflicts
    assert [row["model_group_id"] for row in groups["toyota.camry"]] == ["ice-a", "ice-b"]


def test_same_canonical_id_with_conflicting_identity_is_rejected():
    rows = [
        {"model_group_id": "ice-a", "canonical_model_id": "toyota.camry", "brand": "Toyota", "canonical_name_en": "Camry"},
        {"model_group_id": "ice-b", "canonical_model_id": "toyota.camry", "brand": "Honda", "canonical_name_en": "City"},
    ]
    groups, conflicts = coalesce_candidate_targets(rows)
    assert len(groups["toyota.camry"]) == 2
    assert conflicts == {"toyota.camry": "DUPLICATE_CANONICAL_TARGET_CONFLICT"}


def test_same_brand_and_name_with_two_canonical_ids_is_held_without_generation_evidence():
    rows = [
        {"model_group_id": "ice-a", "canonical_model_id": "toyota.camry_a", "brand": "Toyota", "canonical_name_en": "Camry"},
        {"model_group_id": "ice-b", "canonical_model_id": "toyota.camry_b", "brand": "Toyota", "canonical_name_en": "Camry"},
    ]
    groups, conflicts = coalesce_candidate_targets(rows)
    conflicts.update(find_duplicate_candidate_names(groups))
    assert conflicts == {
        "toyota.camry_a": "DUPLICATE_CANONICAL_NAME_WITHOUT_GENERATION_EVIDENCE",
        "toyota.camry_b": "DUPLICATE_CANONICAL_NAME_WITHOUT_GENERATION_EVIDENCE",
    }


def test_discontinued_catalog_identity_keeps_lifecycle_without_trim_assumptions():
    assert lifecycle({"status": "HISTORICAL"}) == "DISCONTINUED"
    assert lifecycle({"status": "CURRENT"}) == "CURRENT"
    assert lifecycle(None) == "UNKNOWN"


def test_real_m7_manifest_reconciles_frozen_ledger_and_pickup_scopes(tmp_path):
    out = tmp_path / "manifest"
    qa = write_manifest(M7_ZIP, PACKAGE, CATALOG, out)
    assert qa["source"]["model_groups"] == 1200
    assert qa["source"]["registrations"] == 4_141_987
    assert qa["filters"]["eligible_groups"] == 342
    assert qa["filters"]["eligible_registrations"] == 4_123_704
    assert qa["frozen_owner_decisions"]["total"] == 244
    assert qa["frozen_owner_decisions"]["decisions_changed"] == 0
    assert qa["frozen_owner_decisions"]["ledger_decisions_exercised"] == 244
    assert qa["identity_proposals"]["proposal_authority"] == "CANDIDATE_ONLY_NOT_CREATE_AUTHORITY"

    with (out / "existing_identity_links.csv").open(encoding="utf-8", newline="") as stream:
        links = list(csv.DictReader(stream))
    ranger = {(row["reg_type"], row["canonical_id"]) for row in links if row["model_group_id"] == "ford-ford-ranger"}
    assert ("รย.1", "ford.ranger_double_cab") in ranger
    assert ("รย.3", "ford.ranger_cab") in ranger
    source_shadow = list(csv.DictReader((PACKAGE / "shadow_crosswalk_rows.csv").open(encoding="utf-8-sig", newline="")))
    expected_scopes = {(row["reg_type"], row["target_canonical_id"]) for row in source_shadow
                       if row["model_group_id"] == "ford-ford-ranger" and row["disposition"] == "PICKUP_RY_SPLIT_SHADOW"}
    assert ranger == expected_scopes
    with (out / "unresolved_identity_evidence.csv").open(encoding="utf-8", newline="") as stream:
        unresolved = list(csv.DictReader(stream))
    assert any(row["model_group_id"] == "gwm-gwm-poer" and row["reg_type"] == "รย.1"
               and row["evidence_status"] == "UNRESOLVED_EVIDENCE" for row in unresolved)

    ledger_path = PACKAGE / "owner_decision_ledger_244.csv"
    original_sha = "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8"
    assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == original_sha
