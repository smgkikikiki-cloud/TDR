"""The JSON schemas use only the keywords the stdlib validator implements, resolve their refs, and accept/reject what they should."""
from __future__ import annotations

import copy
import json

import pytest

from identity_bootstrap.contract import schema_subset as sc

import ib_support as S

SCHEMAS = S.schemas()


def refs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                yield v
            else:
                yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_uses_only_supported_keywords(name):
    assert sc.unsupported_keywords(SCHEMAS[name]) == []


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_every_ref_resolves(name):
    for ref in refs(SCHEMAS[name]):
        document, _, pointer = ref.partition("#")
        root = SCHEMAS[document] if document else SCHEMAS[name]
        node = root
        for part in [p for p in pointer.split("/") if p]:
            node = node[part]


def test_every_decide_input_validates():
    for c in S.kind("decide"):
        if c.get("validate_input") is False:
            continue
        assert S.validate_input(c["input"]) == [], c["id"]


def test_input_schema_rejects_malformed_snapshots():
    good = copy.deepcopy(S.case_by_id("new.clean-model")["input"])
    mutations = [
        lambda s: s.pop("subjects"),
        lambda s: s["subjects"][0].pop("resolution"),
        lambda s: s["subjects"][0].update(identity_status="maybe"),
        lambda s: s["subjects"][0].update(first_seen_period="2026-13"),
        lambda s: s["subjects"][0].update(units=-1),
        lambda s: s["subjects"][0]["brand"].update(relation="SORT_OF"),
        lambda s: s["subjects"][0]["resolution"].update(outcome="MAYBE"),
        lambda s: s["subjects"][0]["relations"][0].update(name_relation="KIND_OF"),
        lambda s: s.update(contract_version=2),
        lambda s: s["identities"][0].pop("deleted"),
        lambda s: s["lineage"]["events"].append({"event_type": "REPLACE", "old_id": "a", "new_id": "b"}),
        lambda s: s.update(unexpected=1),
    ]
    for mutate in mutations:
        bad = copy.deepcopy(good)
        mutate(bad)
        assert S.validate_input(bad), "schema accepted a malformed snapshot"
    assert S.validate_input(good) == []


def all_decisions():
    for c in S.kind("decide"):
        if "decisions" in c["expect"]:
            for d in S.run_decide(c["input"]):
                yield c["id"], d


def test_every_decision_validates_and_every_event_too():
    count = 0
    for cid, d in all_decisions():
        assert S.validate_decision(d) == [], (cid, S.validate_decision(d))
        if d["write_plan"]:
            assert sc.validate(d["write_plan"]["event"], SCHEMAS["event.schema.json"], registry=SCHEMAS) == [], cid
            count += 1
    assert count >= 15


def test_refusal_records_validate():
    assert S.validate_decision({"record_type": "refusal", "contract_version": 1, "code": "INPUT_SOURCE_VERSION_MISSING", "detail": "x"}) == []
    assert S.validate_decision({"record_type": "refusal", "contract_version": 1, "code": "bad code", "detail": "x"})


def test_decision_schema_binds_outcome_to_payload():
    create = next(d for _, d in all_decisions() if d["outcome"] == "CREATE_IDENTITY")
    hold = next(d for _, d in all_decisions() if d["outcome"] == "HOLD")
    review = next(d for _, d in all_decisions() if d["outcome"] == "IDENTITY_REVIEW")
    for d in (hold, review):
        bad = copy.deepcopy(d)
        bad["write_plan"] = create["write_plan"]
        assert S.validate_decision(bad), "a HOLD/REVIEW record must not carry a plan"
        bad = copy.deepcopy(d)
        bad["identity"] = create["identity"]
        assert S.validate_decision(bad), "a HOLD/REVIEW record must not carry an identity"
    bad = copy.deepcopy(create)
    bad["write_plan"] = None
    assert S.validate_decision(bad), "a CREATE must carry its plan"
    bad = copy.deepcopy(create)
    bad["identity"]["identity_state"] = "PUBLISHED"
    assert S.validate_decision(bad), "Bootstrap can only create DISCOVERED"
    bad = copy.deepcopy(create)
    bad["write_plan"]["event"]["enrichment_state"] = "COMPLETE"
    assert S.validate_decision(bad)


def test_event_schema_requires_the_handoff_payload():
    create = next(d for _, d in all_decisions() if d["outcome"] == "CREATE_IDENTITY")
    event = create["write_plan"]["event"]
    for key in ("canonical_model_id", "canonical_name", "brand_id", "identity_state", "source", "aliases", "creation", "enrichment_hints"):
        bad = copy.deepcopy(event)
        del bad[key]
        assert sc.validate(bad, SCHEMAS["event.schema.json"], registry=SCHEMAS), key


def test_every_case_validates_against_the_case_schema():
    for c in S.cases():
        assert sc.validate(c, SCHEMAS["case.schema.json"], registry=SCHEMAS) == [], (c["id"], sc.validate(c, SCHEMAS["case.schema.json"], registry=SCHEMAS))


def test_corpus_ids_are_unique_and_json_is_canonical_lines():
    ids = [c["id"] for c in S.cases()]
    assert len(ids) == len(set(ids))
    for line in (S.CONTRACT_DIR / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)
