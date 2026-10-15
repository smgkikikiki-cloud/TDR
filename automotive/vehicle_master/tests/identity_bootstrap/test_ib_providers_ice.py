"""The Ice adapter converts Ice meaning into the generic snapshot, and nothing else."""
from __future__ import annotations

import pytest

import ib_support as S
from identity_bootstrap.providers import ice


def test_buddhist_periods_become_gregorian():
    assert ice.to_gregorian("2569-09") == "2026-09"
    assert ice.to_gregorian("2564-01") == "2021-01"


def test_identity_status_follows_ices_markers():
    assert ice.identity_status("toyota-hilux-revo") == "settled"
    assert ice.identity_status("audi-a3-sb-35-tfsi-s-line__provisional") == "provisional"
    assert ice.identity_status("NISSAN|BVL2RTYD23FHP A") == "unmapped_name"
    assert ice.identity_status("ISUZU|ไม่ระบุ") == "unmapped_name"


def test_lineage_types_map_and_an_unknown_type_is_refused_not_guessed():
    rows = [{"old_model_group_id": "a", "new_model_group_id": "b", "type": "เปลี่ยนรหัส"}, {"old_model_group_id": "c", "new_model_group_id": "d", "type": "รวม"},
            {"old_model_group_id": "e", "new_model_group_id": "f", "type": "แยก"}]
    assert [e["event_type"] for e in ice.lineage_events(rows)] == ["RENAME", "MERGE", "SPLIT"]
    with pytest.raises(ValueError):
        ice.lineage_events([{"old_model_group_id": "a", "new_model_group_id": "b", "type": "ลบ"}])


def _build(dims, **kw):
    brand = {"raw": "JAECOO", "brand_id": "jaecoo", "relation": "EXACT"}
    return ice.build_snapshot(source_label="ice:2569-09:v3:M7.0", policy_version=2, as_of_period_be="2569-09", dims=dims,
                              first_seen_be={r["model_group_id"]: "2567-12" for r in dims}, id_changes=kw.get("id_changes", []), identities=[],
                              brand_for=lambda raw: brand, resolution_for=lambda row: {"outcome": "NO_CANDIDATE", "reason_codes": []}, relations_for=lambda row: [])


ROW = {"model_group_id": "jaecoo-jaecoo-j6", "model_name": "Jaecoo J6", "brand": "JAECOO", "reg_total_all": "8659", "segment": "SUV", "body": "SUV"}


def test_snapshot_shape_and_provenance():
    snap = _build([ROW])
    assert S.validate_input(snap) == []
    s = snap["subjects"][0]
    assert snap["as_of_period"] == "2026-09" and s["first_seen_period"] == "2024-12"
    assert s["evidence"] == [{"kind": "PROVIDER_IDENTITY", "ref": "ice:2569-09:v3:M7.0#model_group/jaecoo-jaecoo-j6"}]
    assert s["units"] == 8659.0 and s["provider"] == "ice"
    assert s["provider_hints"] == {"body": "SUV", "segment": "SUV"}, "dims claims travel only as UNVERIFIED hints"


def test_blank_and_unspecified_hints_are_not_offered():
    snap = _build([{**ROW, "segment": "ไม่ระบุ", "body": ""}])
    assert "provider_hints" not in snap["subjects"][0]


def test_lineage_source_is_declared_only_when_events_exist():
    assert _build([ROW])["lineage"] == {"declared_identity_change": False, "source_present": True, "events": []}
    snap = _build([ROW], id_changes=[{"old_model_group_id": "a", "new_model_group_id": "b", "type": "แยก"}])
    assert snap["lineage"]["declared_identity_change"] is True and snap["lineage"]["events"][0]["event_type"] == "SPLIT"


def test_the_adapter_computes_no_decision_and_contains_no_policy_vocabulary():
    text = open(ice.__file__, encoding="utf-8").read()
    for needle in ("CREATE_IDENTITY", "IDENTITY_REVIEW", "hatchback", "sport", "premium"):
        assert needle not in text
