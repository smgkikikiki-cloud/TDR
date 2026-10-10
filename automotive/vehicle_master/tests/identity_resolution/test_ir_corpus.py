"""Identity Resolution contract v1: the golden corpus.

The corpus is the executable specification of the engine that does not exist yet. These tests prove the corpus is well-formed,
covers the taxonomy / the reason codes / the defect classes the owner named, and — for everything that is pure arithmetic — that the
written expectations are correct, by recomputing them with an independent reference (ir_reference.py).
"""
from __future__ import annotations

import collections
import re

import pytest

from identity_resolution.contract import schema_subset as sc

import ir_reference as R
import ir_support as S

CASES = S.cases()
BY_ID = {c["id"]: c for c in CASES}


def ids_of(kind):
    return [c["id"] for c in CASES if c["kind"] == kind]


def case(case_id):
    return BY_ID[case_id]


# ------------------------------------------------------------------------------------------------ well-formedness


def test_corpus_is_not_empty_and_every_kind_is_present():
    kinds = collections.Counter(c["kind"] for c in CASES)
    expected = set(S.schemas()["case.schema.json"]["properties"]["kind"]["enum"])
    assert set(kinds) == expected, expected ^ set(kinds)
    assert len(CASES) >= 300


def test_every_case_validates_against_the_case_schema():
    schemas = S.schemas()
    for item in CASES:
        errors = sc.validate(item, schemas["case.schema.json"], registry=schemas, root=schemas["case.schema.json"])
        assert not errors, (item["id"], errors[:3])


def test_ids_are_unique_and_prefixed_by_kind():
    assert len(BY_ID) == len(CASES)
    for item in CASES:
        assert item["id"].split(".")[0] == item["kind"], item["id"]


def test_every_origin_is_used_and_r6_cases_say_what_they_reproduce():
    origins = collections.Counter(c["origin"] for c in CASES)
    assert set(origins) == {"owner_report_r6", "ice_m7_data", "design"}
    for item in CASES:
        if item["origin"] == "owner_report_r6" and item["kind"] in ("resolve", "classify"):
            assert item.get("note") or item.get("legacy_note") or item["title"], item["id"]


def test_taxonomy_ids_named_by_cases_exist_and_every_taxonomy_id_is_covered():
    known = {e["id"] for e in S.taxonomy()["entries"]}
    covered = set()
    for item in CASES:
        assert set(item["taxonomy"]) <= known, (item["id"], set(item["taxonomy"]) - known)
        covered |= set(item["taxonomy"])
    assert not known - covered, sorted(known - covered)


def test_every_reason_code_is_asserted_by_some_case():
    asserted = set()
    for item in CASES:
        asserted |= S.asserted_codes(item["expect"])
    unasserted = set(S.codes()) - asserted
    assert not unasserted, f"reason codes no case ever expects: {sorted(unasserted)}"


def test_expectations_only_name_registered_codes():
    for item in CASES:
        for code in S.referenced_codes(item["expect"]):
            assert code in S.codes(), (item["id"], code)


def test_the_owner_named_edge_cases_each_have_an_end_to_end_case():
    """The task's list, mapped to taxonomy ids; each needs at least one resolve/classify/lineage case, not only unit vectors."""
    concepts = {
        "time-window bias": ["SER-01", "SER-02"], "granularity mismatch": ["GRAN-01", "GRAN-02"], "weak brand normalization": ["BRND-01", "BRND-07"],
        "D-Max -> MU-X": ["NAME-02"], "brand aliasing": ["BRND-02", "BRND-03"], "generation mismatch": ["GRAN-03"],
        "split": ["LIN-03", "LIN-04"], "merge": ["LIN-02"], "provisional groups": ["SUBJ-01"], "one-to-many / many-to-one": ["SER-17", "GRAN-01", "CARD-02"],
        "aliases": ["NAME-09"], "same-name / different-generation": ["GRAN-04"], "missing canonical target": ["CARD-05", "CARD-06", "CARD-08"],
        "conflicting candidates": ["CARD-01", "CARD-04"], "low data": ["SER-09", "SER-10", "CARD-09"], "AUTO is not APPROVED": ["STATE-04", "STATE-01"],
        "provider structure outranks statistics": ["AUTH-01", "LIN-16"], "APPROVED/LOCKED never overwritten": ["STATE-01", "STATE-02", "LIN-13", "LIN-14"],
    }
    end_to_end = {"resolve", "classify", "lineage"}
    for concept, tax_ids in concepts.items():
        for tax_id in tax_ids:
            hits = [c for c in CASES if tax_id in c["taxonomy"] and c["kind"] in end_to_end]
            assert hits, f"{concept}: no end-to-end case covers {tax_id}"


# ------------------------------------------------------------------------------------------------ expectation consistency


def _decision_expectations():
    for item in CASES:
        if item["kind"] == "resolve" and "decisions" in item["expect"]:
            for subject, expectation in item["expect"]["decisions"].items():
                yield item["id"], subject, expectation
        elif item["kind"] == "classify":
            yield item["id"], None, item["expect"]


def test_decision_expectations_are_internally_consistent():
    registry = S.codes()
    for case_id, subject, exp in _decision_expectations():
        label = f"{case_id}:{subject}"
        outcome = exp["outcome"]
        if "proposed_status" in exp:
            wanted = {"AUTO": "AUTO", "PROPOSE": "PROPOSED"}.get(outcome, "NONE")
            assert exp["proposed_status"] == wanted, label
        if "primary_code" in exp:
            spec = registry[exp["primary_code"]]
            assert spec["kind"] == "decision" and outcome in spec.get("primary_for", []), (label, exp["primary_code"], outcome)
        for code in exp.get("include", []) + exp.get("exclude", []):
            assert registry[code]["kind"] in ("decision", "both"), (label, code)
        if outcome == "AUTO":
            assert exp.get("review_required", False) is False, label
            assert len(exp.get("target_ids", [None])) == 1, label
        if outcome in ("NO_CANDIDATE", "INSUFFICIENT_DATA", "SUPPRESSED", "AMBIGUOUS"):
            assert exp.get("target_ids", []) == [], label
        if exp.get("method") == "SERIES":
            assert outcome in ("AUTO", "PROPOSE"), label
        for write in exp.get("writes", []):
            assert write["action"] in S.WRITE_ACTIONS


def test_a_capped_strong_series_expectation_lists_a_blocker_or_a_subject_flag():
    for case_id, subject, exp in _decision_expectations():
        if exp.get("primary_code") == "PROPOSE_SERIES_STRONG_CAPPED":
            blockers = [c for c in exp.get("include", []) if S.codes()[c]["roles"] != ["info"] and "blocking" in S.codes()[c]["roles"]]
            assert blockers, (case_id, subject)


def test_evidence_paths_in_expectations_exist_in_the_decision_schema():
    decision = S.schemas()["decision.schema.json"]["$defs"]
    evidence = decision["evidence"]["properties"]

    def evidence_fields(section):
        return set(evidence[section]["anyOf"][0]["properties"])

    valid_comparison = set(decision["comparison"]["properties"]) | {"common_window.from", "common_window.to", "common_window.months"}
    for case_id, subject, exp in _decision_expectations():
        for path in exp.get("evidence", {}):
            parts = path.split(".")
            if parts[0] == "evidence":
                assert parts[1] in evidence and parts[2] in evidence_fields(parts[1]), (case_id, path)
            else:
                assert parts[0] == "comparison" and ".".join(parts[1:]) in valid_comparison, (case_id, path)


def test_lineage_expectations_use_structural_codes_for_the_right_operation():
    registry = S.codes()
    expectations = []
    for item in CASES:
        if item["kind"] == "lineage":
            expectations += item["expect"].get("operations", [])
        if item["kind"] == "resolve":
            expectations += item["expect"].get("operations", [])
    assert expectations
    for op in expectations:
        spec = registry[op["primary_code"]]
        assert spec["kind"] in ("structural", "both") and op["op"] in spec["primary_for"], op
        for code in op.get("include", []):
            assert registry[code]["kind"] in ("structural", "both"), code


def test_lineage_refusals_use_refusal_codes_and_applied_keys_name_real_events():
    for item in CASES:
        if item["kind"] == "lineage":
            if "refusal" in item["expect"]:
                assert S.codes()[item["expect"]["refusal"]["code"]]["kind"] == "refusal"
            lineage = item["input"]["lineage"]
            keys = {f"{e['event_type']}:{e['old_id']}>{e['new_id']}" for e in lineage["events"]}
            assert set(lineage.get("applied_event_keys", [])) <= keys, item["id"]
        if item["kind"] == "resolve" and "refusal" in item["expect"]:
            assert S.codes()[item["expect"]["refusal"]["code"]]["kind"] == "refusal", item["id"]


def test_resolve_snapshots_are_self_consistent():
    for item in CASES:
        if item["kind"] != "resolve":
            continue
        snapshot = item["input"]
        ids = [s["entity_id"] for s in snapshot["subjects"]]
        if "refusal" not in item["expect"] or item["expect"]["refusal"]["code"] != "INPUT_DUPLICATE_SUBJECT_ID":
            assert len(ids) == len(set(ids)), item["id"]
        target_ids = [t["target_id"] for t in snapshot["targets"]]
        assert len(target_ids) == len(set(target_ids)), item["id"]
        if "decisions" in item["expect"]:
            assert set(item["expect"]["decisions"]) <= set(ids), item["id"]


def test_classify_evidence_tuples_tell_the_truth():
    """A hand-built tuple must agree with the gate math it claims: STRONG/WEAK are recomputed from the numbers."""
    policy = S.policy()
    for item in CASES:
        if item["kind"] != "classify":
            continue
        for candidate in item["input"]["candidates"]:
            series = candidate["evidence"]["series"]
            if series is None:
                continue
            stats = {k: series[k] for k in ("common_months", "joint_nonzero_months", "subject_units", "target_units")}
            if series["state"] == "UNAVAILABLE":
                assert series["unavailable_reason"] in S.codes() and S.codes()[series["unavailable_reason"]]["effect"] == "series_unavailable", item["id"]
                assert series["correlation"] is None and series["ratio"] is None and series["monthly_fit_share"] is None, item["id"]
            else:
                assert series["unavailable_reason"] is None, item["id"]
                stats.update(correlation=series["correlation"], ratio=series["ratio"], monthly_fit_share=series["monthly_fit_share"])
                state, _ = R.series_gate(stats, policy)
                assert state == series["state"], (item["id"], state, series["state"])


# ------------------------------------------------------------------------------------------------ arithmetic expectations, recomputed


def _in(value, expectation):
    if isinstance(expectation, dict):
        return (("min" not in expectation or value >= expectation["min"]) and ("max" not in expectation or value <= expectation["max"]))
    return value == expectation


@pytest.mark.parametrize("case_id", ids_of("window"))
def test_window_expectations_match_the_reference(case_id):
    item = case(case_id)
    result = R.compare_series(item["input"]["subject_series"], item["input"]["target_series"], S.policy(), item["input"].get("max_months"))
    expect = item["expect"]
    if "refusal" in expect:
        assert result["refusal"] == expect["refusal"]
        return
    assert result["refusal"] is None
    assert result["common_window"] == expect["common_window"]
    assert result["state"] == expect["series_state"]
    for code in expect.get("include", []):
        assert code in result["codes"], (code, result["codes"])
    for code in expect.get("exclude", []):
        assert code not in result["codes"]
    for entry in expect.get("excluded", []):
        assert entry in result["excluded"], entry
    for key, expectation in expect.get("series", {}).items():
        assert _in(result["stats"][key], expectation), (key, result["stats"][key], expectation)
    assert not [e for e in result["excluded"] if e["reason"] not in
                {"outside_common_coverage", "leading_inactive", "trailing_inactive", "partial_period", "outside_max_window", "unobserved_in_subject", "unobserved_in_target"}]


def test_the_engine_never_zero_fills_in_the_reference_either():
    """A null month must leave the comparison; it must never change the unit totals."""
    base = next(c for c in CASES if c["id"] == "window.interior-unobserved-not-zero")
    result = R.compare_series(base["input"]["subject_series"], base["input"]["target_series"], S.policy())
    target = base["input"]["target_series"]
    kept_target_units = sum(c for i, c in enumerate(target["counts"]) if c is not None and R.pstr(R.pidx(target["start"]) + i) in set(result["periods"]))
    assert result["stats"]["target_units"] == kept_target_units
    assert result["common_window"]["months"] == len(result["periods"]) == 22


@pytest.mark.parametrize("case_id", ids_of("series_gate"))
def test_series_gate_expectations(case_id):
    item = case(case_id)
    state, codes = R.series_gate(item["input"], S.policy())
    assert state == item["expect"]["state"]
    for code in item["expect"].get("include", []):
        assert code in codes, (code, codes)
    for code in item["expect"].get("exclude", []):
        assert code not in codes, (code, codes)


@pytest.mark.parametrize("case_id", ids_of("band"))
def test_band_expectations(case_id):
    item = case(case_id)
    assert R.band(item["input"]["dimension"], item["input"]["value"], S.policy()) == item["expect"]["band"]


@pytest.mark.parametrize("case_id", ids_of("protection"))
def test_write_matrix_expectations(case_id):
    item = case(case_id)
    assert R.write_action(item["input"]["existing_state"], item["input"]["decision"], item["input"]["fingerprint"], S.policy()) == item["expect"]["action"]


def test_the_write_matrix_is_exercised_cell_by_cell():
    policy = S.policy()
    expected = set()
    for state, row in policy["state"]["write_matrix"].items():
        for decision, cell in row.items():
            for flag in (["unchanged", "changed"] if isinstance(cell, dict) else ["not_applicable"]):
                expected.add((state, decision, flag))
    got = {(c["input"]["existing_state"], c["input"]["decision"], c["input"]["fingerprint"]) for c in CASES if c["kind"] == "protection"}
    assert got == expected


def test_protected_rows_are_never_mutated_by_any_protection_case():
    for item in CASES:
        if item["kind"] == "protection" and item["input"]["existing_state"] in ("APPROVED", "LOCKED"):
            assert item["expect"]["action"] == "BLOCK_REPORT" and item["expect"]["mutates_protected_row"] is False


@pytest.mark.parametrize("case_id", ids_of("lifecycle_relation"))
def test_lifecycle_expectations(case_id):
    item = case(case_id)
    relation, share = R.lifecycle_relation(item["input"]["subject_series"], item["input"]["generations"], item["input"]["as_of_period"], S.policy())
    assert relation == item["expect"]["lifecycle"]
    if "share" in item["expect"]:
        assert _in(share, item["expect"]["share"])


@pytest.mark.parametrize("case_id", ids_of("body_relation"))
def test_body_expectations(case_id):
    item = case(case_id)
    assert R.body_relation(item["input"]["provider_body"], item["input"]["tdr_body_type"], S.policy()) == item["expect"]["body"]


def test_resolve_series_expectations_match_the_reference():
    """Where a resolve case asserts window/series numbers for a single-target outcome, recompute them from the snapshot."""
    checked = 0
    for item in CASES:
        if item["kind"] != "resolve" or "decisions" not in item["expect"]:
            continue
        for subject_id, exp in item["expect"]["decisions"].items():
            paths = exp.get("evidence", {})
            if not paths or len(exp.get("target_ids", [])) != 1:
                continue
            subject = next(s for s in item["input"]["subjects"] if s["entity_id"] == subject_id)
            target = next(t for t in item["input"]["targets"] if t["target_id"] == exp["target_ids"][0])
            result = R.compare_series(subject.get("series"), target.get("series"), S.policy())
            for path, expectation in paths.items():
                if path.startswith("comparison.common_window."):
                    assert _in(result["common_window"][path.rsplit(".", 1)[1]], expectation), (item["id"], path)
                    checked += 1
                elif path.startswith("evidence.series."):
                    field = path.rsplit(".", 1)[1]
                    assert _in(result["stats"][field], expectation), (item["id"], path)
                    checked += 1
    assert checked >= 6


# ------------------------------------------------------------------------------------------------ fingerprints


@pytest.mark.parametrize("case_id", ids_of("fingerprint"))
def test_fingerprint_vectors(case_id):
    item = case(case_id)
    payload, expect = item["input"]["payload"], item["expect"]
    if expect.get("error"):
        with pytest.raises(ValueError, match=expect["error"]):
            R.fingerprint(payload)
        return
    digest = R.fingerprint(payload)
    if "sha256" in expect:
        assert digest == expect["sha256"]
    if "same_digest_as" in expect:
        assert digest == R.fingerprint(case(expect["same_digest_as"])["input"]["payload"])
    if "different_digest_from" in expect:
        assert digest != R.fingerprint(case(expect["different_digest_from"])["input"]["payload"])


def test_fingerprint_payloads_carry_no_floats_and_use_declared_versions():
    for item in CASES:
        if item["kind"] == "fingerprint" and not item["expect"].get("error"):
            payload = item["input"]["payload"]
            assert payload["v"] == ("decision-fp/1" if item["input"]["fingerprint_kind"] == "decision" else "evidence-fp/1")
            R.canonical_json(payload)   # raises on any float


def test_the_evidence_fingerprint_has_no_window_and_no_source_version():
    for item in CASES:
        if item["kind"] == "fingerprint" and item["input"]["fingerprint_kind"] == "evidence" and not item["expect"].get("error"):
            keys = set(item["input"]["payload"])
            assert not keys & {"source_version", "comparison_periods", "policy"}, "the suppression key must not move with a package or a rolling window"


# ------------------------------------------------------------------------------------------------ the R6 failure classes, pinned


def test_dmax_is_not_mux_in_every_layer():
    assert case("name_relation.dmax-vs-mux")["expect"]["relation"] == "CONTRADICTION"
    assert case("classify.veto-contradiction")["expect"]["outcome"] == "NO_CANDIDATE"
    decision = case("resolve.dmax-not-mux")["expect"]["decisions"]["isuzu-isuzu-d-max"]
    assert decision["outcome"] == "NO_CANDIDATE" and "NAME_CONTRADICTION" in decision["include"]
    assert "legacy_note" in case("resolve.dmax-not-mux"), "the legacy mechanism must stay documented"


def test_window_bias_cases_pin_the_common_end_anchor():
    exp = case("resolve.window-tdr-ends-early")["expect"]["decisions"]["toyota-yaris-ativ"]["evidence"]
    assert exp["comparison.common_window.to"] == "2026-03", "anchor is the common window end, not Ice's 2026-09"
    window = case("window.tdr-ends-early-anchor-on-common-end")["expect"]
    assert window["common_window"]["to"] == "2026-03" and "SER_COVERAGE_ASYMMETRIC" in window["include"]


def test_no_resolve_case_expects_a_protected_state_to_be_written():
    for case_id, subject, exp in _decision_expectations():
        for write in exp.get("writes", []):
            if exp["outcome"] == "PROTECTED_HOLD":
                assert write["action"] in ("INSERT_PROPOSED", "REFRESH_EVIDENCE"), (case_id, write)
