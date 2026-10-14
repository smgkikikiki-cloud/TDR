#!/usr/bin/env python3
"""Reconcile the frozen 114-target plan against a private full Vehicle Master backup.

The input backup must remain outside the repository. Output contains only target
IDs, matching canonical IDs, counts, and source hashes; it never writes source rows.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import pathlib
import sys
import unicodedata


ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKUP_PATH = pathlib.Path(os.environ.get("TDR_VM_PRIVATE_BACKUP_GZIP", "")).resolve()
PLAN_PATH = ROOT / "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/materialization_plan_114.json"
SHADOW_PATH = ROOT / "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/shadow_identity_materialization.csv"
LEDGER_PATH = ROOT / "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/owner_decision_ledger_244.csv"
OUTPUT_PATH = ROOT / "docs/vehicle-db/phase1d/identity_target_reconciliation_2026-10-14.json"
EXPECTED_GZIP_SHA = "8b7dc88cf42c27516ec08ddf170173feff85891ac655caa9a6f3eb5511d8b962"
EXPECTED_LEDGER_SHA = "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(value: object, brand: str = "") -> str:
    text = unicodedata.normalize("NFKC", str(value or "").strip().lower())
    prefix = unicodedata.normalize("NFKC", str(brand or "").strip().lower())
    if prefix and (text.startswith(prefix + " ") or text.startswith(prefix + ":")):
        text = text[len(prefix) + 1 :]
    return "".join(char for char in text if unicodedata.category(char)[0] in "LN")


def main() -> int:
    if not os.environ.get("TDR_VM_PRIVATE_BACKUP_GZIP") or not BACKUP_PATH.is_file():
        raise SystemExit("TDR_VM_PRIVATE_BACKUP_GZIP must point to the verified private .json.gz backup")
    if BACKUP_PATH.is_relative_to(ROOT):
        raise SystemExit("PRIVATE_BACKUP_MUST_REMAIN_OUTSIDE_REPOSITORY")

    compressed = BACKUP_PATH.read_bytes()
    compressed_hash = sha256(compressed)
    if compressed_hash != EXPECTED_GZIP_SHA:
        raise SystemExit("PRIVATE_BACKUP_GZIP_SHA256_MISMATCH")
    source_bytes = gzip.decompress(compressed)
    envelope = json.loads(source_bytes)
    payload = envelope.get("payload") or {}
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    payload_hash = sha256(payload_bytes)
    if payload_hash != "c51c20966be5f49dd0fe9a953793e666f6becf0f4d27a986158b6805e7659dad":
        raise SystemExit("PRIVATE_BACKUP_PAYLOAD_SHA256_MISMATCH")
    if len(payload.get("tables", [])) != 15 or sum(payload.get("row_counts", {}).values()) != 28319:
        raise SystemExit("PRIVATE_BACKUP_TABLE_OR_ROW_COUNT_MISMATCH")

    ledger_bytes = LEDGER_PATH.read_bytes()
    if sha256(ledger_bytes) != EXPECTED_LEDGER_SHA:
        raise SystemExit("FROZEN_OWNER_LEDGER_CHANGED")
    with LEDGER_PATH.open(encoding="utf-8-sig", newline="") as source:
        ledger = list(csv.DictReader(source))
    if len(ledger) != 244:
        raise SystemExit("FROZEN_OWNER_DECISION_COUNT_CHANGED")
    frozen_create_ids = {
        row["decision_id"] for row in ledger if row["owner_action"] == "OWNER_CREATE_IDENTITY"
    }
    if len(frozen_create_ids) != 38:
        raise SystemExit("FROZEN_OWNER_CREATE_COUNT_CHANGED")

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if len(plan) != 114 or len({row["canonical_target_id"] for row in plan}) != 114:
        raise SystemExit("MISSING_IDENTITY_TARGET_COUNT_OR_DUPLICATE")
    models = payload["data"]["vehicle_models"]
    brands = {row["canonical_id"]: row for row in payload["data"]["vehicle_brands"]}
    model_ids = {row["canonical_id"] for row in models}
    with SHADOW_PATH.open(encoding="utf-8-sig", newline="") as source:
        materialization = list(csv.DictReader(source))
    if len(materialization) != 114:
        raise SystemExit("SHADOW_MATERIALIZATION_COUNT_CHANGED")
    units_by_target: dict[str, int] = {}
    for row in materialization:
        target = row["canonical_model_id"]
        units_by_target[target] = units_by_target.get(target, 0) + int(row["registration_units_m7_0"])
    if len(units_by_target) != 114 or set(units_by_target) != {row["canonical_target_id"] for row in plan}:
        raise SystemExit("SHADOW_TARGET_MEMBERSHIP_MISMATCH")
    conflicts: list[dict[str, str]] = []
    dispositions: list[dict[str, object]] = []
    stats = {
        "frozen_owner_create_no_normalized_name_or_alias_conflict": 0,
        "frozen_owner_create_conflict_hold": 0,
        "independent_candidate_no_conflict_and_brand_present": 0,
        "independent_candidate_conflict_hold": 0,
        "independent_candidate_brand_missing": 0,
    }
    decision_refs: set[str] = set()

    for candidate in plan:
        target = candidate["canonical_target_id"]
        ref_values = candidate.get("frozen_owner_decision_refs") or []
        if len(ref_values) != 1 or ref_values[0] in decision_refs:
            raise SystemExit("OWNER_DECISION_REFERENCE_MISSING_OR_DUPLICATED")
        decision_ref = ref_values[0]
        decision_refs.add(decision_ref)
        is_frozen_create = decision_ref in frozen_create_ids
        brand_id = target.split(".", 1)[0]
        brand = brands.get(brand_id)
        brand_name = (brand or {}).get("name_en", "")
        wanted_name = (candidate.get("proposed_values") or {}).get("name_en", "")
        hits: set[str] = set()
        if target in model_ids:
            hits.add(target)
        if brand:
            wanted = normalize(wanted_name, brand_name)
            for model in models:
                if model.get("brand_id") != brand_id:
                    continue
                values: list[object] = [model.get("name_en"), model.get("name_th")]
                aliases = (model.get("payload") or {}).get("aliases") or []
                if isinstance(aliases, list):
                    values.extend(aliases)
                elif isinstance(aliases, dict):
                    values.extend(aliases.values())
                elif isinstance(aliases, str):
                    values.append(aliases)
                if wanted and any(isinstance(value, str) and normalize(value, brand_name) == wanted for value in values):
                    hits.add(model["canonical_id"])

        if is_frozen_create:
            key = "frozen_owner_create_conflict_hold" if hits else "frozen_owner_create_no_normalized_name_or_alias_conflict"
        elif hits:
            key = "independent_candidate_conflict_hold"
        elif not brand:
            key = "independent_candidate_brand_missing"
        else:
            key = "independent_candidate_no_conflict_and_brand_present"
        stats[key] += 1
        units = units_by_target[target]
        dispositions.append({
            "canonical_target_id": target,
            "source_ref": decision_ref,
            "registration_units_m7_0": units,
            "decision_state": "FROZEN_OWNER_CREATE" if is_frozen_create else "CANDIDATE_ONLY_NO_OWNER_CREATE_APPROVAL",
            "disposition": "READY_FOR_ADMIN_APPROVAL" if is_frozen_create and not hits and brand else "HOLD_WITH_EXACT_REASON",
            "candidate_review_status": (
                "FROZEN_OWNER_CREATE_UNCHANGED" if is_frozen_create else "CANDIDATE_SCREEN_PASS_NO_COLLISION"
                if not hits and brand else "CANDIDATE_HOLD_EXISTING_ALIAS_COLLISION"
                if hits else "CANDIDATE_HOLD_BRAND_IDENTITY_MISSING"
            ),
            "reason": (
                "EXISTING_CANONICAL_ID_OR_NORMALIZED_SAME_BRAND_NAME_ALIAS_COLLISION"
                if hits else "BRAND_IDENTITY_NOT_PRESENT_IN_VERIFIED_VEHICLE_MASTER"
                if not brand else "NO_FROZEN_OWNER_CREATE_DECISION_NEW_APPROVAL_REQUIRED"
                if not is_frozen_create else "NO_CANONICAL_OR_NORMALIZED_SAME_BRAND_NAME_ALIAS_COLLISION_IN_VERIFIED_BACKUP"
            ),
            "approvals": "FROZEN_OWNER_CREATE_REQUIRES_ADMIN_APPLY_AUTH" if is_frozen_create else "CANDIDATE_ONLY_REQUIRES_NEW_OWNER_CREATE_APPROVAL_AND_ADMIN_APPLY_AUTH",
        })
        if hits:
            for existing_id in sorted(hits):
                conflicts.append({
                    "target_id": target,
                    "source_ref": decision_ref,
                    "review_class": "FROZEN_OWNER_CREATE" if is_frozen_create else "INDEPENDENT_REVIEW_CANDIDATE",
                    "existing_canonical_id": existing_id,
                    "reason": "CANONICAL_ID_COLLISION" if existing_id == target else "NORMALIZED_SAME_BRAND_NAME_ALIAS_COLLISION",
                    "materialization": "HOLD_PENDING_GOVERNED_ALIAS_IDENTITY_REPAIR",
                })

    if len(decision_refs & frozen_create_ids) != 38:
        raise SystemExit("NOT_ALL_FROZEN_OWNER_CREATE_DECISIONS_RECONCILED")
    if len(decision_refs) - len(frozen_create_ids) != 76:
        raise SystemExit("UNEXPECTED_UNFROZEN_CANDIDATE_COUNT")
    unit_summary = {"total": sum(units_by_target.values()), "frozen_owner_create": 0, "candidate_only": 0}
    disposition_units: dict[str, int] = {}
    for row in dispositions:
        group = "frozen_owner_create" if row["decision_state"] == "FROZEN_OWNER_CREATE" else "candidate_only"
        unit_summary[group] += int(row["registration_units_m7_0"])
        label = str(row["disposition"])
        disposition_units[label] = disposition_units.get(label, 0) + int(row["registration_units_m7_0"])
    if unit_summary != {"total": 98025, "frozen_owner_create": 3112, "candidate_only": 94913}:
        raise SystemExit("M7_TARGET_REGISTRATION_RECONCILIATION_FAILED")
    if stats != {
        "frozen_owner_create_no_normalized_name_or_alias_conflict": 34,
        "frozen_owner_create_conflict_hold": 4,
        "independent_candidate_no_conflict_and_brand_present": 65,
        "independent_candidate_conflict_hold": 9,
        "independent_candidate_brand_missing": 2,
    }:
        raise SystemExit("M7_TARGET_COLLISION_CLASSIFICATION_CHANGED")
    if disposition_units != {"READY_FOR_ADMIN_APPROVAL": 2862, "HOLD_WITH_EXACT_REASON": 95163}:
        raise SystemExit("M7_TARGET_DISPOSITION_UNIT_RECONCILIATION_FAILED")
    if len(conflicts) != 13:
        raise SystemExit("M7_TARGET_COLLISION_COUNT_CHANGED")

    report = {
        "schema": "tdr.vehicle-db.phase1d.identity-target-reconciliation.v1",
        "source": {
            "backup_gzip_sha256": compressed_hash,
            "decompressed_backup_sha256": sha256(source_bytes),
            "payload_sha256": payload_hash,
            "tables": len(payload["tables"]),
            "rows": sum(payload["row_counts"].values()),
            "brands_checked": len(brands),
            "catalog_models_checked": len(models),
            "raw_catalog_rows_in_report": False,
        },
        "frozen_inputs": {
            "owner_decisions": len(ledger),
            "owner_ledger_sha256": sha256(ledger_bytes),
            "frozen_owner_create_decisions": len(frozen_create_ids),
            "decision_changes": 0,
        },
        "candidate_reconciliation": {
            "total_missing_identity_targets": len(plan),
            "unique_target_count": len({row["canonical_target_id"] for row in plan}),
            "unique_decision_reference_count": len(decision_refs),
            "counts": stats,
            "registration_units": unit_summary,
            "registration_units_by_disposition": disposition_units,
            "dispositions": dispositions,
            "conflicts": conflicts,
            "ready_for_admin_approval_is_not_create_authorization": True,
            "candidate_only_targets_are_not_ready_for_admin_apply_until_new_owner_create_approval": True,
            "none_are_production_create_approvals": True,
            "existing_identity_reuse_targets": 0,
            "all_target_registrations_reconciled_once": True,
            "ford_ranger_raptor": "HOLD_UNCHANGED",
        },
    }
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(OUTPUT_PATH.relative_to(ROOT)),
        "targets": len(plan),
        "frozen_owner_create": len(frozen_create_ids),
        "independent_candidates": len(decision_refs) - len(frozen_create_ids),
        "counts": stats,
        "registration_units": unit_summary,
        "registration_units_by_disposition": disposition_units,
        "collision_records": len(conflicts),
        "raw_catalog_rows_written": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
