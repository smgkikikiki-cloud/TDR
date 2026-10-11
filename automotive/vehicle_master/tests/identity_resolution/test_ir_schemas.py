"""Identity Resolution contract v1: the JSON schemas, and the stdlib validator that enforces them."""
from __future__ import annotations

import copy

import pytest

from identity_resolution.contract import schema_subset as sc

import ir_support as S

SCHEMA_NAMES = ("record.schema.json", "decision.schema.json", "case.schema.json", "capabilities.schema.json")


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schemas_use_only_keywords_the_validator_implements(name):
    """If a schema used a keyword the stdlib validator ignores, validation would silently under-check."""
    assert sc.unsupported_keywords(S.schemas()[name]) == []


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_ref_resolves(name):
    registry = S.schemas()
    refs: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref":
                    refs.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(registry[name])
    assert refs
    for ref in refs:
        target, _ = sc._resolve(ref, registry[name], registry)
        assert isinstance(target, dict), ref


def test_schemas_are_valid_draft_2020_12_when_jsonschema_is_installed():
    jsonschema = pytest.importorskip("jsonschema", reason="CI installs PyYAML but not jsonschema; the stdlib validator is the gate")
    for name, schema in S.schemas().items():
        jsonschema.Draft202012Validator.check_schema(schema)


def test_stdlib_validator_agrees_with_jsonschema_on_the_corpus_when_installed():
    jsonschema = pytest.importorskip("jsonschema", reason="optional cross-check")
    registry = S.schemas()
    from referencing import Registry, Resource  # jsonschema >= 4.18
    resources = [(f"tdr:identity-resolution:v1:{n.split('.')[0]}", Resource.from_contents(registry[n])) for n in registry]
    resources += [(n, Resource.from_contents(registry[n])) for n in registry]
    reg = Registry().with_resources(resources)
    validator = jsonschema.Draft202012Validator(registry["case.schema.json"], registry=reg)
    for case in S.cases():
        assert not list(validator.iter_errors(case)), case["id"]


# ------------------------------------------------------------------------------------------------ the validator itself


def test_validator_basics():
    schema = {"type": "object", "required": ["a"], "additionalProperties": False,
              "properties": {"a": {"type": "integer", "minimum": 1}, "b": {"enum": ["x", "y"]}}}
    assert sc.validate({"a": 1}, schema) == []
    assert sc.validate({}, schema)
    assert sc.validate({"a": 0}, schema)
    assert sc.validate({"a": True}, schema), "booleans are not integers"
    assert sc.validate({"a": 1, "c": 2}, schema)
    assert sc.validate({"a": 1, "b": "z"}, schema)


def test_validator_if_then_oneof_and_nullable_types():
    schema = {"oneOf": [{"type": "string"}, {"type": "null"}]}
    assert sc.validate("x", schema) == [] and sc.validate(None, schema) == [] and sc.validate(1, schema)
    conditional = {"if": {"properties": {"k": {"const": 1}}, "required": ["k"]}, "then": {"required": ["v"]}}
    assert sc.validate({"k": 1}, conditional) and sc.validate({"k": 1, "v": 0}, conditional) == [] and sc.validate({"k": 2}, conditional) == []
    assert sc.validate(1.0, {"type": "number"}) == [] and sc.validate(1.5, {"type": "integer"})


# ------------------------------------------------------------------------------------------------ decision schema invariants


def _resolution(**over):
    evidence = {"brand": None, "name": None, "series": None, "attributes": None, "structure": None, "margin": None, "parts": None}
    record = {
        "record_type": "resolution", "contract_version": "v1", "policy": {"version": "1.0.0", "digest": "0" * 64, "binding": False}, "provider": "ice",
        "source_version": {"label": "ice:2569-09:v3:M7.0"}, "subject": {"entity_kind": "model_group", "entity_id": "x"},
        "outcome": "NO_CANDIDATE", "proposed_status": "NONE", "method": "NONE", "target": {"kind": "tdr_model", "ids": []}, "link": {"type": None, "set_id": None},
        "reason_codes": [{"code": "NO_CANDIDATE_EMPTY_POOL", "role": "primary"}], "evidence": evidence, "comparison": None,
        "existing_state": None, "alternatives": [], "review": {"required": False, "queue": "none", "priority": "normal", "question": None},
        "writes": [], "fingerprints": {"decision": "a" * 64, "evidence": "b" * 64},
    }
    record.update(over)
    return record


def _errors(record):
    schemas = S.schemas()
    return sc.validate(record, schemas["decision.schema.json"], registry=schemas, root=schemas["decision.schema.json"])


def test_a_minimal_no_candidate_resolution_is_valid():
    assert _errors(_resolution()) == []


def test_the_engine_can_never_emit_approved_locked_or_rejected():
    for status in ("APPROVED", "LOCKED", "REJECTED"):
        assert _errors(_resolution(proposed_status=status)), status


def test_outcome_status_invariants_are_in_the_schema():
    assert _errors(_resolution(outcome="AUTO", proposed_status="NONE"))
    assert _errors(_resolution(outcome="PROPOSE", proposed_status="AUTO"))
    assert _errors(_resolution(outcome="NO_CANDIDATE", proposed_status="PROPOSED"))
    ok_auto = _resolution(outcome="AUTO", proposed_status="AUTO", method="SERIES", target={"kind": "tdr_model", "ids": ["t"]}, link={"type": "EQUIVALENT", "set_id": None},
                          reason_codes=[{"code": "AUTO_ALL_GATES_PASSED", "role": "primary"}])
    assert _errors(ok_auto) == []
    assert _errors({**ok_auto, "review": {"required": True, "queue": "crosswalk_review", "priority": "normal", "question": None}}), "AUTO needs no review"
    assert _errors({**ok_auto, "target": {"kind": "tdr_model", "ids": ["a", "b"]}}), "AUTO links exactly one target; bundles are PROPOSE only"
    assert _errors({**ok_auto, "link": {"type": "PART_OF", "set_id": None}}), "only an EQUIVALENT claim can be AUTO"
    assert _errors({**ok_auto, "link": {"type": "COMPOSED_OF", "set_id": "ls1-" + "a" * 24}}), "a link set is never AUTO"
    assert _errors(_resolution(outcome="AMBIGUOUS", proposed_status="NONE", alternatives=[])), "AMBIGUOUS lists at least two alternatives"


def test_the_engine_never_zero_fills():
    comparison = {"requested_max_months": 24, "subject_coverage": None, "target_coverage": None, "common_window": None,
                  "periods": [], "excluded_periods": [], "engine_zero_filled_periods": ["2025-01"],
                  "absent_rows": {"subject": None, "target": None, "unconfirmed_gap_months": 0}}
    assert _errors(_resolution(comparison=comparison)), "engine_zero_filled_periods must always be empty"
    assert _errors(_resolution(comparison={**comparison, "engine_zero_filled_periods": []})) == []


def test_reason_codes_need_a_valid_shape_and_at_least_one_entry():
    assert _errors(_resolution(reason_codes=[]))
    assert _errors(_resolution(reason_codes=[{"code": "lowercase", "role": "primary"}]))
    assert _errors(_resolution(reason_codes=[{"code": "X_Y", "role": "winner"}]))


def test_structural_operation_and_refusal_records():
    op = {"record_type": "structural_operation", "contract_version": "v1", "policy": {"version": "1.0.0", "digest": "0" * 64, "binding": False}, "provider": "ice",
          "source_version": {"label": "l"}, "op": "REDIRECT", "event_type": "RENAME", "old_id": "a", "new_id": "b", "hint_target_ids": [],
          "reason_codes": [{"code": "LIN_RENAME_FOLLOWED", "role": "primary"}], "authority": "PROVIDER_STRUCTURE",
          "affects_protected": {"approved": 0, "locked": 0}, "requires_owner_ack": False, "fingerprint": "c" * 64}
    assert _errors(op) == []
    assert _errors({**op, "authority": "STATISTICAL_SERIES"}), "lineage is always provider-structure authority"
    refusal = {"record_type": "refusal", "contract_version": "v1", "policy": {"version": "1.0.0", "digest": "0" * 64, "binding": False}, "provider": "ice",
               "code": "INPUT_SOURCE_VERSION_MISSING", "detail": "no label"}
    assert _errors(refusal) == []
    assert _errors({**refusal, "record_type": "resolution"})


def test_input_snapshot_requires_a_source_version_and_declares_unobserved_as_null():
    schemas = S.schemas()
    snapshot = copy.deepcopy(next(c for c in S.cases() if c["id"] == "resolve.clean-auto-city")["input"])
    assert sc.validate(snapshot, schemas["record.schema.json"]["$defs"]["snapshot"], registry=schemas, root=schemas["record.schema.json"]) == []
    snapshot["subjects"][0]["series"]["counts"][3] = None   # unobserved is legal
    assert sc.validate(snapshot, schemas["record.schema.json"]["$defs"]["snapshot"], registry=schemas, root=schemas["record.schema.json"]) == []
    del snapshot["source_version"]
    assert sc.validate(snapshot, schemas["record.schema.json"]["$defs"]["snapshot"], registry=schemas, root=schemas["record.schema.json"])


# ------------------------------------------------------------------------------------------------ rev 2: link types, link sets, capabilities, binding


def _propose(link, ids, set_id=None):
    return _resolution(outcome="PROPOSE", proposed_status="PROPOSED", method="SERIES", target={"kind": "tdr_model", "ids": ids}, link={"type": link, "set_id": set_id},
                       review={"required": True, "queue": "crosswalk_review", "priority": "normal", "question": None},
                       reason_codes=[{"code": "PROPOSE_NAME_MATCH_SERIES_NOT_STRONG", "role": "primary"}])


def test_link_type_and_target_cardinality_are_in_the_schema():
    set_id = "ls1-" + "a" * 24
    assert _errors(_propose("EQUIVALENT", ["t"])) == [] and _errors(_propose("PART_OF", ["t"])) == []
    assert _errors(_propose("COMPOSED_OF", ["a", "b"], set_id)) == []
    assert _errors(_propose("COMPOSED_OF", ["a", "b", "c"], set_id)) == []
    assert _errors(_propose("COMPOSED_OF", ["a"], set_id)), "a composed claim has at least two targets"
    assert _errors(_propose("COMPOSED_OF", ["a", "b"], None)), "a link set has a set id"
    assert _errors(_propose("PART_OF", ["a", "b"])), "a part is part of ONE target"
    assert _errors(_propose("EQUIVALENT", ["t"], set_id)), "only a link set has a set id"
    assert _errors(_propose("SIBLING", ["t"])), "unknown link type"
    assert _errors(_resolution(link={"type": "EQUIVALENT", "set_id": None})), "no target, no link type"
    assert _errors(_propose(None, ["t"])), "a PROPOSE asserts some relationship"


def test_writes_and_alternatives_carry_the_link_type_and_set_id():
    set_id = "ls1-" + "a" * 24
    write = {"target_id": "a", "action": "INSERT_PROPOSED", "to_status": "PROPOSED", "link_type": "COMPOSED_OF", "set_id": set_id}
    assert _errors({**_propose("COMPOSED_OF", ["a", "b"], set_id), "writes": [write]}) == []
    assert _errors({**_propose("COMPOSED_OF", ["a", "b"], set_id), "writes": [{k: v for k, v in write.items() if k != "link_type"}]}), "a write without a link type is ambiguous"
    assert _errors({**_propose("COMPOSED_OF", ["a", "b"], set_id), "writes": [{**write, "link_type": "SIBLING"}]})


def test_every_record_says_whether_the_policy_was_binding():
    record = _resolution()
    del record["policy"]["binding"]
    assert _errors(record), "policy.binding is required (invariant I16)"
    assert _errors(_resolution(policy={"version": "1.0.0", "digest": "0" * 64, "binding": "no"}))


def test_the_comparison_reports_what_it_assumed_about_missing_rows():
    comparison = {"requested_max_months": 24, "subject_coverage": None, "target_coverage": None, "common_window": None, "periods": [], "excluded_periods": [],
                  "engine_zero_filled_periods": []}
    assert _errors(_resolution(comparison=comparison)), "absent_rows is required"
    ref = {"source": "tdr_registrations", "semantics": "UNKNOWN", "confirmed": False}
    ok = {**comparison, "absent_rows": {"subject": None, "target": ref, "unconfirmed_gap_months": 3}}
    assert _errors(_resolution(comparison=ok)) == []
    assert _errors(_resolution(comparison={**comparison, "absent_rows": {"subject": None, "target": {**ref, "semantics": "GUESS"}, "unconfirmed_gap_months": 3}}))
    reasons = {"period": "2025-01", "reason": "unconfirmed_absent_row_in_target"}
    assert _errors(_resolution(comparison={**ok, "excluded_periods": [reasons]})) == []


def test_the_record_schema_accepts_absent_rows_and_link_fields():
    schemas = S.schemas()
    snapshot = copy.deepcopy(next(c for c in S.cases() if c["id"] == "resolve.absent-row-gap-caps-auto")["input"])
    root = schemas["record.schema.json"]
    assert sc.validate(snapshot, root["$defs"]["snapshot"], registry=schemas, root=root) == []
    snapshot["targets"][0]["series"]["absent_rows"]["semantics"] = "ASSUMED_ZERO"
    assert sc.validate(snapshot, root["$defs"]["snapshot"], registry=schemas, root=root)
    mapping = {"subject_id": "s", "target_id": "t", "state": "PROPOSED", "link_type": "COMPOSED_OF", "set_id": "ls1-" + "a" * 24, "set_size": 2}
    assert sc.validate(mapping, root["$defs"]["existing_mapping"], registry=schemas, root=root) == []
    assert sc.validate({**mapping, "link_type": "SIBLING"}, root["$defs"]["existing_mapping"], registry=schemas, root=root)
    assert sc.validate({"subject_id": "s", "target_id": "t", "state": "AUTO"}, root["$defs"]["existing_mapping"], registry=schemas, root=root) == [], "a legacy row has no link type"
