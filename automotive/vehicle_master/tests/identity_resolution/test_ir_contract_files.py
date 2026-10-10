"""Identity Resolution contract v1: structural integrity of policy.yaml, reason_codes.yaml and taxonomy.yaml.

These tests check the contract is internally consistent. They do not (cannot yet) check an engine: there is none.
"""
from __future__ import annotations

import re

import pytest

from identity_resolution.contract import loader, render

import ir_support as S

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


# ------------------------------------------------------------------------------------------------ loading


def test_yaml_loader_rejects_duplicate_keys(tmp_path):
    bad = tmp_path / "dup.yaml"
    bad.write_text("a: 1\na: 2\n", encoding="utf-8")
    with bad.open(encoding="utf-8") as handle, pytest.raises(loader.DuplicateKeyError):
        import yaml
        yaml.load(handle, Loader=loader._StrictLoader)


def test_contract_files_exist():
    for name in ("SPEC.md", "policy.yaml", "reason_codes.yaml", "taxonomy.yaml", "decision.schema.json", "record.schema.json",
                 "case.schema.json", "cases.jsonl"):
        assert (S.CONTRACT_DIR / name).is_file(), name


# ------------------------------------------------------------------------------------------------ policy


def test_policy_header():
    header = S.policy()["policy"]
    assert SEMVER.match(header["version"])
    assert header["contract_version"] == "v1"
    assert header["status"] == "draft_for_owner_review"


def test_policy_provenance_covers_every_key():
    policy = S.policy()
    allowed = {"inherited", "observed", "proposal", "assumption"}
    assert set(policy["provenance"].values()) <= allowed
    for path, tag in policy["provenance"].items():
        # the tag must point at something that exists
        assert any(leaf == path or leaf.startswith(path + ".") for leaf, _ in render.policy_leaves(policy)), f"provenance for unknown key {path}"
    for path, _ in render.policy_leaves(policy):
        assert render.provenance_of(path, policy["provenance"]) in allowed, f"policy key {path} has no provenance"


def test_alias_provenance_covers_every_alias():
    policy = S.policy()
    ids = {a["id"] for a in policy["aliases"]["brand"]} | {m["id"] for m in policy["aliases"]["model"]}
    assert set(policy["alias_provenance"]) == ids
    assert set(policy["alias_provenance"].values()) <= {"owner_seed", "observed", "assumption"}


def test_write_matrix_is_complete_and_valid():
    matrix = S.policy()["state"]["write_matrix"]
    assert set(matrix) == set(S.PAIR_STATES)
    for state, row in matrix.items():
        assert set(row) == {"AUTO", "PROPOSE", "ABSENT"}, state
        for decision, cell in row.items():
            cells = cell.values() if isinstance(cell, dict) else [cell]
            if isinstance(cell, dict):
                assert set(cell) == {"fingerprint_unchanged", "fingerprint_changed"}
                assert state == "REJECTED"
            for action in cells:
                assert action in S.WRITE_ACTIONS, (state, decision, action)


def test_write_matrix_never_lets_the_engine_touch_protected_rows():
    matrix = S.policy()["state"]["write_matrix"]
    for state in ("APPROVED", "LOCKED"):
        assert set(matrix[state].values()) == {"BLOCK_REPORT"}


def test_write_matrix_never_produces_auto_from_a_rejection_or_a_proposal_without_evidence():
    matrix = S.policy()["state"]["write_matrix"]
    assert matrix["REJECTED"]["AUTO"]["fingerprint_changed"] == "REOPEN_AS_PROPOSED"   # AUTO is not APPROVED, and a rejection is not undone by a machine
    assert matrix["AUTO"]["ABSENT"] == "DEMOTE_TO_PROPOSED"                              # an AUTO row is revocable, never silently kept or deleted
    assert matrix["PROPOSED"]["ABSENT"] == "MARK_STALE"
    assert "DELETE" not in " ".join(S.WRITE_ACTIONS)


def test_series_thresholds_are_sane():
    series = S.policy()["series"]
    strong = series["strong"]
    assert 0 < strong["correlation_min"] <= 1
    assert 0 < strong["ratio_min"] < 1 < strong["ratio_max"]
    for key in ("common_months", "joint_nonzero_months", "units_each_side"):
        assert 0 < series["minimums"]["propose"][key] <= series["minimums"]["auto"][key], key
    assert series["minimums"]["auto"]["joint_nonzero_months"] <= series["minimums"]["auto"]["common_months"]
    assert series["minimums"]["propose"]["joint_nonzero_months"] <= series["minimums"]["propose"]["common_months"]
    assert series["window"]["max_months"] >= series["minimums"]["auto"]["common_months"]
    assert 0 < series["monthly_fit"]["min_share_of_months"] <= 1
    assert S.policy()["quantization"]["places"] >= 2


def test_inherited_thresholds_match_the_owner_approved_document():
    """VEHICLE_DB_V3 §14.2: correlation >= 0.98, ratio 0.9-1.1, last 24 months. Changing these is an owner decision."""
    policy = S.policy()
    assert policy["series"]["strong"] == {"correlation_min": 0.98, "ratio_min": 0.9, "ratio_max": 1.1}
    assert policy["series"]["window"]["max_months"] == 24
    inherited = {path for path, tag in policy["provenance"].items() if tag == "inherited"}
    assert {"series.strong", "series.window.max_months"} <= inherited


def test_band_edges_are_strictly_ascending():
    for dimension, edges in S.policy()["fingerprint"]["bands"].items():
        assert edges == sorted(edges) and len(set(edges)) == len(edges), dimension
    assert set(S.policy()["fingerprint"]["bands"]) == {"correlation", "ratio", "name_score", "common_months"}


def test_relation_lists_use_known_relations():
    policy = S.policy()
    name = policy["lexical"]["name"]
    for key in ("auto_relations", "candidate_relations", "veto_relations"):
        assert set(name[key]) <= set(S.NAME_RELATIONS), key
    assert set(name["auto_relations"]) <= set(name["candidate_relations"])
    assert not set(name["veto_relations"]) & set(name["candidate_relations"])
    candidates = policy["candidates"]
    assert set(candidates["brand_relations_allowed"]) <= set(S.BRAND_RELATIONS)
    assert set(candidates["brand_relations_auto_eligible"]) <= set(candidates["brand_relations_allowed"])
    assert "MISMATCH" not in candidates["brand_relations_allowed"] and "UNKNOWN" not in candidates["brand_relations_allowed"]
    assert set(candidates["bundle"]["member_name_relations"]) <= set(S.NAME_RELATIONS)
    assert set(policy["granularity"]["provider_finer"]["subject_name_relations"]) <= set(S.NAME_RELATIONS)


def test_ranking_lists_are_total_orders_of_known_values():
    ranking = S.policy()["candidates"]["ranking"]
    assert sorted(ranking["tier_order"]) == sorted(S.RANK_TIERS), "tier_order must name every ranking tier exactly once"
    assert sorted(ranking["series_state_order"]) == ["STRONG", "UNAVAILABLE", "WEAK"]
    assert sorted(ranking["lifecycle_order"]) == ["PARTIAL", "UNKNOWN", "WITHIN"]
    assert sorted(ranking["name_relation_order"]) == sorted(set(S.NAME_RELATIONS) - {"SIBLING", "CONTRADICTION"})
    assert ranking["tier_order"][0] == "auto_eligible", "an AUTO-eligible candidate must outrank everything else"


def test_alias_classes_are_well_formed():
    aliases = S.policy()["aliases"]["brand"]
    ids = [a["id"] for a in aliases]
    assert len(ids) == len(set(ids))
    assert {a["relation"] for a in aliases} <= {"SAME", "RELABEL", "RELATED"}

    def compact(text: str) -> str:
        return re.sub(r"[^a-z0-9฀-๿]", "", text.casefold())

    seen: dict[str, str] = {}
    for alias in aliases:
        if alias["relation"] == "RELATED":
            continue
        for member in alias["members"]:
            key = compact(member)
            assert key, member
            assert key not in seen, f"brand key {key!r} is in two SAME/RELABEL classes: {seen.get(key)} and {alias['id']}"
            seen[key] = alias["id"]
    for alias in aliases:
        assert len(alias["members"]) >= 2, alias["id"]
    for entry in S.policy()["aliases"]["model"]:
        assert set(entry["brand_alias_ids"]) <= set(ids)
        assert all(len(pair) == 2 for pair in entry["pairs"])


def test_body_compatibility_uses_tdr_body_types():
    from vehreg.taxonomy import BodyType
    valid = {member.value for member in BodyType}
    for label, types in S.policy()["attributes"]["body"]["compatibility"].items():
        assert set(types) <= valid, (label, set(types) - valid)
        assert "OTHER" not in types


def test_lifecycle_thresholds():
    lifecycle = S.policy()["attributes"]["lifecycle"]
    assert 0 <= lifecycle["disjoint_max_share"] < lifecycle["within_min_share"] <= 1
    assert lifecycle["grace_months"] >= 0


def test_review_routing_is_complete_and_points_at_real_queues():
    routing = S.policy()["review"]["routing"]
    assert set(routing) == set(S.OUTCOMES)
    assert set(routing.values()) <= {"crosswalk_review", "structure_review", "discovery", "none"}
    assert routing["AUTO"] == "none", "an AUTO link needs no review queue"
    for code in S.policy()["review"]["high_priority_codes"] + S.policy()["review"]["discovery_subject_flags"]:
        assert code in S.codes(), code


def test_lineage_protected_settings_use_allowed_values():
    protected = S.policy()["lineage"]["protected"]
    assert set(protected) == {"approved", "locked"}
    assert set(protected.values()) <= {"follow_with_lineage", "require_owner_ack"}
    assert protected["locked"] == "require_owner_ack", "LOCKED is the owner's explicit freeze; changing this default is an owner decision"


def test_never_auto_statuses_are_known_identity_statuses():
    assert set(S.policy()["subject_quality"]["never_auto_identity_statuses"]) <= {"provisional", "unmapped_name"}


# ------------------------------------------------------------------------------------------------ registry


def test_registry_entries_are_well_formed():
    registry = S.registry()
    assert registry["outcomes"] == S.OUTCOMES
    assert registry["operations"] == S.OPERATIONS
    for code, spec in registry["codes"].items():
        assert re.fullmatch(r"[A-Z][A-Z0-9_]+", code), code
        assert spec["kind"] in {"decision", "structural", "both", "refusal"}, code
        assert spec["roles"] and set(spec["roles"]) <= {"primary", "blocking", "supporting", "info"}, code
        assert spec["effect"] in {"none", "cap_proposed", "veto_candidate", "series_unavailable", "name_unavailable", "forces_review",
                                  "blocks_write", "suppresses", "refuses_run", "emits_operation"}, code
        assert spec["summary"].strip(), code
        has_primary_for = bool(spec.get("primary_for"))
        if spec["kind"] != "refusal":     # a refusal is not an outcome or an operation, so it has no primary_for
            assert has_primary_for == ("primary" in spec["roles"]), f"{code}: roles and primary_for disagree"
        if spec["kind"] == "decision":
            assert set(spec.get("primary_for", [])) <= set(S.OUTCOMES), code
        if spec["kind"] in ("structural", "both"):
            assert set(spec.get("primary_for", [])) <= set(S.OPERATIONS), code
        if spec["kind"] == "refusal":
            assert spec["roles"] == ["primary"] and spec["effect"] == "refuses_run", code


def test_every_outcome_and_operation_has_a_primary_code():
    registry = S.registry()["codes"]
    for outcome in S.OUTCOMES:
        assert [c for c, s in registry.items() if s["kind"] == "decision" and outcome in s.get("primary_for", [])], outcome
    for operation in S.OPERATIONS:
        assert [c for c, s in registry.items() if s["kind"] in ("structural", "both") and operation in s.get("primary_for", [])], operation


def test_registry_matches_the_decision_schema_enums():
    decision = S.schemas()["decision.schema.json"]
    assert decision["$defs"]["resolution"]["properties"]["outcome"]["enum"] == S.OUTCOMES
    assert decision["$defs"]["structural_operation"]["properties"]["op"]["enum"] == S.OPERATIONS
    assert decision["$defs"]["write"]["properties"]["action"]["enum"] == S.WRITE_ACTIONS
    matrix_actions = set()
    for row in S.policy()["state"]["write_matrix"].values():
        for cell in row.values():
            matrix_actions.update(cell.values() if isinstance(cell, dict) else [cell])
    assert matrix_actions <= set(S.WRITE_ACTIONS)
    evidence = decision["$defs"]["evidence"]["properties"]
    assert evidence["name"]["anyOf"][0]["properties"]["relation"]["enum"] == S.NAME_RELATIONS
    assert evidence["brand"]["anyOf"][0]["properties"]["relation"]["enum"] == S.BRAND_RELATIONS


def test_codes_named_in_policy_exist():
    for outcome_code in S.policy()["review"]["high_priority_codes"]:
        assert outcome_code in S.codes()


# ------------------------------------------------------------------------------------------------ taxonomy


def test_taxonomy_entries_are_well_formed():
    taxonomy = S.taxonomy()
    areas = set(taxonomy["areas"])
    ids = [e["id"] for e in taxonomy["entries"]]
    assert len(ids) == len(set(ids))
    for entry in taxonomy["entries"]:
        assert re.fullmatch(r"[A-Z]+-\d{2}", entry["id"]), entry["id"]
        assert entry["id"].split("-")[0] in areas, entry["id"]
        assert entry["origin"] in {"owner_report_r6", "ice_m7_data", "design"}, entry["id"]
        for field in ("title", "evidence", "handling"):
            assert entry[field].strip(), (entry["id"], field)
        assert isinstance(entry["codes"], list)
        for code in entry["codes"]:
            assert code in S.codes(), (entry["id"], code)


def test_every_reason_code_belongs_to_some_taxonomy_entry():
    used = {code for entry in S.taxonomy()["entries"] for code in entry["codes"]}
    assert not set(S.codes()) - used, sorted(set(S.codes()) - used)


def test_taxonomy_ids_are_dense_within_each_area():
    by_area: dict[str, list[int]] = {}
    for entry in S.taxonomy()["entries"]:
        area, number = entry["id"].split("-")
        by_area.setdefault(area, []).append(int(number))
    for area, numbers in by_area.items():
        assert sorted(numbers) == list(range(1, len(numbers) + 1)), f"{area} ids must be 01..N without gaps (renumbering is a corpus change)"


def test_the_owner_reported_r6_defect_classes_are_in_the_taxonomy():
    """The four defect classes the owner named from the first R6 run, plus the ones named in the task."""
    entries = S.taxonomy()["entries"]
    assert len([e for e in entries if e["origin"] == "owner_report_r6"]) >= 6
    text = " ".join(f'{e["title"]} {e["evidence"]} {e["handling"]}'.lower() for e in entries)
    for needle in ("time-window", "granularity", "brand normalization", "d-max", "conflicting candidates"):
        assert needle in text, needle
