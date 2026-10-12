from __future__ import annotations

import json

from tools import ice_crosswalk_r6_offline_recovery as recovery


def test_frozen_244_ledger_has_exact_action_split_and_no_duplicate_ids():
    ledger = recovery.build_owner_ledger()
    assert len(ledger) == 244
    assert len({row["model_group_id"] for row in ledger}) == 244
    assert {action: sum(row["owner_action"] == action for row in ledger) for action in {
        "OWNER_LINK_EXISTING", "KEEP_EXISTING_AUTO", "OWNER_EXCLUDE_FROM_COUNT", "OWNER_CREATE_IDENTITY"
    }} == {
        "OWNER_LINK_EXISTING": 92,
        "KEEP_EXISTING_AUTO": 63,
        "OWNER_EXCLUDE_FROM_COUNT": 51,
        "OWNER_CREATE_IDENTITY": 38,
    }


def test_real_m7_shadow_replay_respects_owner_targets_and_fixed_denominator():
    rows, targets = recovery.build_shadow_rows()
    unmatched = recovery.build_unmatched_classification(rows)
    qa = recovery.build_qa(rows, targets, unmatched)
    assert qa["source_group_count"] == 1200
    assert qa["fixed_denominator_units"] == 4_141_987
    assert qa["owner_decision_rows_loaded_and_respected"] == 244
    assert qa["owner_decision_output_mismatches"] == 0
    assert qa["owner_re_review_required"] == 0
    assert qa["unmatched_group_count"] == 675
    assert qa["target_met_fixed_denominator"] is True
    assert qa["fixed_denominator_coverage_pct"] >= 99.1

    serena = [row for row in rows if row["model_group_id"] == "nissan-serena"]
    assert serena and all(row["disposition"] == "OWNER_APPROVED_LINK" for row in serena)
    assert all(row["target_canonical_id"] == "nissan.serena" for row in serena)
    package = json.loads(recovery.OWNER_TARGETS.read_text(encoding="utf-8"))
    assert package["owner_approved_identity_overrides"]["nissan-serena"] == "nissan.serena"


def test_collision_resolution_uses_exact_mazda_name_and_preserves_numeric_lock():
    rows, _ = recovery.build_shadow_rows()
    cx30 = [row for row in rows if row["model_group_id"] == "mazda-mazda-cx-30"]
    assert cx30
    assert all(row["disposition"] == "OWNER_APPROVED_LINK" for row in cx30)
    assert all(row["target_canonical_id"] == "mazda.cx30" for row in cx30)
    assert all("unapproved structure proposal" in row["reason"] for row in cx30)


def test_pickup_shadow_splits_ry1_ry2_and_ry3_without_promoting_old_parent():
    rows, _ = recovery.build_shadow_rows()
    triton = {row["reg_type"]: row for row in rows if row["model_group_id"] == "mitsubishi-triton"}
    assert triton["รย.1"]["target_canonical_id"] == "mitsubishi.triton_double_cab"
    assert triton["รย.2"]["target_canonical_id"] == "mitsubishi.triton_double_cab"
    assert triton["รย.3"]["target_canonical_id"] == "mitsubishi.triton_cab"
    assert all(row["disposition"] == "PICKUP_RY_SPLIT_SHADOW" for row in triton.values())
