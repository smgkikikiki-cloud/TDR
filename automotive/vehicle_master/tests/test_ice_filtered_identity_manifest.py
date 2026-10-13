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
    catalog_sha_before = hashlib.sha256(CATALOG.read_bytes()).hexdigest()
    qa = write_manifest(M7_ZIP, PACKAGE, CATALOG, out)
    assert hashlib.sha256(CATALOG.read_bytes()).hexdigest() == catalog_sha_before
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
    assert len(unresolved) == 22
    assert sum(int(row["registrations"]) for row in unresolved) == 1_376
    assert sum(int(row["registrations"]) for row in unresolved
               if row["reason"].startswith("UNIDENTIFIABLE_SOURCE_DATA")) == 380
    assert sum(int(row["registrations"]) for row in unresolved
               if not row["reason"].startswith("UNIDENTIFIABLE_SOURCE_DATA")) == 996

    with (out / "final_scope_dispositions.csv").open(encoding="utf-8", newline="") as stream:
        scopes = list(csv.DictReader(stream))
    assert len(scopes) == 1_407
    assert sum(int(row["registrations"]) for row in scopes) == 4_141_987
    assert sum(int(row["registrations"]) for row in scopes
               if row["eligibility"] == "ELIGIBLE") == 4_123_704
    source_unknown = [row for row in scopes if row["eligibility"] == "ELIGIBLE"
                      and row["disposition_detail"] == "UNIDENTIFIABLE_SOURCE_DATA"]
    assert len(source_unknown) == 9
    assert sum(int(row["registrations"]) for row in source_unknown) == 380

    # The owner-approved pickup mappings remain class-specific; unresolved
    # classes cannot inherit a neighboring class target or a parent fallback.
    unresolved_keys = {(row["model_group_id"], row["reg_type"]) for row in unresolved}
    assert {("gwm-gwm-poer", "รย.1"), ("gwm-gwm-poer", "รย.2"),
            ("suzuki-carry", "รย.1"), ("suzuki-carry", "รย.2"),
            ("tata-tata-xenon", "รย.1"), ("tata-tata-xenon", "รย.3"),
            ("toyota-hilux-champ", "รย.1"), ("toyota-hilux-champ", "รย.2")} <= unresolved_keys
    assert ("ford-ford-ranger", "รย.9") in unresolved_keys
    assert ("isuzu-isuzu-d-max", "รย.9") in unresolved_keys

    with (out / "identity_alias_repair_proposals.csv").open(encoding="utf-8", newline="") as stream:
        repairs = list(csv.DictReader(stream))
    bmw_530e = next(row for row in repairs if row["source_model_group_id"] == "bmw-bmw-530e")
    assert (bmw_530e["existing_canonical_id"], bmw_530e["alias_to_remove"],
            bmw_530e["proposed_canonical_id"]) == ("bmw.bmw_5", "530e", "bmw.530e")
    assert bmw_530e["repair_status"] == "PROPOSAL_ONLY_NOT_CATALOG_MUTATION"
    assert bmw_530e["owner_decision_changed"] == "False"
    with (out / "new_basic_identity_proposals.csv").open(encoding="utf-8", newline="") as stream:
        proposals = {row["canonical_id"]: row for row in csv.DictReader(stream)}
    assert proposals["bmw.530e"]["segment"] == "D-segment"
    assert proposals["bmw.530e"]["body_type"] == "Sedan"
    assert proposals["bmw.530e"]["powertrain"] == "UNKNOWN"
    assert "M7.0:dims/model_group.csv:bmw-bmw-530e" in proposals["bmw.530e"]["source_references"]
    assert proposals["nex.nps"]["brand_record_status"] == "BRAND_CREATE_OR_RECONCILIATION_REQUIRED"

    with (out / "eligible_model_groups.csv").open(encoding="utf-8", newline="") as stream:
        groups = list(csv.DictReader(stream))
    assert any(row["identity_status"] == "PARTIALLY_MAPPED" for row in groups)
    assert all(row["owner_decisions_changed"] == "False" for row in groups)
    simulation = qa["identity_classification"]["registration_weighted_readiness_simulation"]
    assert simulation["simulated_candidate_ready_registrations"] == 4_122_328
    assert simulation["simulated_candidate_ready_pct"] == 99.966632
    production = qa["identity_classification"]["production_approved_servable"]
    assert production["newly_approved_or_servable_registrations_from_this_manifest"] == 0
    assert qa["identity_classification"]["starting_unresolved_59_scope_recovery"]["resolved_scope_count"] == 37

    ledger_path = PACKAGE / "owner_decision_ledger_244.csv"
    original_sha = "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8"
    assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == original_sha
