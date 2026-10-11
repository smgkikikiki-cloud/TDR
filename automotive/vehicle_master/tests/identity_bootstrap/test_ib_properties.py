"""Properties every conforming engine MUST satisfy on EVERY decide case of the corpus (SPEC §2, §16)."""
from __future__ import annotations

import copy
import json
import random

import pytest

import ib_reference as R
import ib_support as S
from identity_bootstrap import engine

DECIDE = [c for c in S.kind("decide") if "decisions" in c["expect"]]
IDS = [c["id"] for c in DECIDE]
POLICY = S.policy()
INV = {"SUBJECT_FINER": "SUBJECT_COARSER", "SUBJECT_COARSER": "SUBJECT_FINER"}


@pytest.fixture(params=sorted(S.IMPLS), autouse=True)
def impl(request):
    global IMPL
    IMPL = request.param
    return request.param


IMPL = "oracle"


def run(snapshot, policy=None):
    return S.run_decide(copy.deepcopy(snapshot), policy, IMPL)


def strip_review(decisions):
    out = copy.deepcopy(decisions)
    for d in out:
        d["review"].pop("priority_band")
        d["review"].pop("alert")
    return out


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_volume_is_never_authority(case):
    base = strip_review(run(case["input"]))
    for units in (None, 0, 3, 499, 500, 10_000_000):
        snap = copy.deepcopy(case["input"])
        for s in snap["subjects"]:
            if units is None:
                s.pop("units", None)
            else:
                s["units"] = units
        assert strip_review(run(snap)) == base, f"outcome changed with units={units}"


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_decisions_are_independent_of_order_and_relation_orientation(case):
    base = run(case["input"])
    for seed in range(4):
        rnd = random.Random(seed)
        snap = copy.deepcopy(case["input"])
        for key in ("subjects", "identities", "bindings"):
            rnd.shuffle(snap[key])
        rnd.shuffle(snap["lineage"]["events"])
        for s in snap["subjects"]:
            rnd.shuffle(s.get("relations", []))
            rnd.shuffle(s.get("evidence", []))
        if seed % 2:      # state every subject<->subject relation from the other side instead
            by = {(s["provider"], s["entity_id"]): s for s in snap["subjects"]}
            for s in snap["subjects"]:
                keep = []
                for r in s.get("relations", []):
                    peer = by.get((r.get("peer_provider", s["provider"]), r["peer_id"]))
                    if r["peer_kind"] == "SUBJECT" and peer is not None:
                        peer.setdefault("relations", []).append(
                            {"peer_kind": "SUBJECT", "peer_id": s["entity_id"], "peer_provider": s["provider"], "name_relation": INV.get(r["name_relation"], r["name_relation"])})
                    else:
                        keep.append(r)
                s["relations"] = keep
        assert run(snap) == base, f"order/orientation changed the decisions (seed {seed})"


def _mask_source(decisions):
    out = []
    for d in decisions:
        out.append({"subject": d["subject"], "outcome": d["outcome"], "primary": d["primary_reason"], "codes": d["reason_codes"], "identity": d["identity"],
                    "fingerprints": d["fingerprints"], "tier": d["evidence_basis"]["tier"], "kinds": d["evidence_basis"]["kinds"],
                    "cleared": d["evidence_basis"]["cleared_flags"], "group": d["batch_group"], "creator": d["creator_type"],
                    "ops": [o["idempotency_key"] for o in d["write_plan"]["operations"]] if d["write_plan"] else None,
                    "event_id": d["write_plan"]["event"]["event_id"] if d["write_plan"] else None})
    return out


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_source_version_changes_nothing_but_provenance(case):
    base = run(case["input"])
    snap = copy.deepcopy(case["input"])
    snap["source_version"]["label"] = "ice:2570-01:v9:M99.0"
    for s in snap["subjects"]:
        for e in s.get("evidence", []):
            e["ref"] = e["ref"].replace("ice:2569-10:v1:M8.0", "ice:2570-01:v9:M99.0")
    changed = run(snap)
    assert _mask_source(changed) == _mask_source(base)
    for a, b in zip(base, changed):
        assert a["source_version"] != b["source_version"]


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_decisions_are_deterministic_and_json_stable(case):
    a, b = run(case["input"]), run(case["input"])
    assert a == b and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_canonical_id_does_not_depend_on_the_provider_id(case):
    if case["input"].get("admin_directives"):
        pytest.skip("a directive binds to the provider id by design")
    base = run(case["input"])
    snap = copy.deepcopy(case["input"])
    ren = {}
    for s in snap["subjects"]:
        ren[(s["provider"], s["entity_id"])] = "renamed::" + s["entity_id"]
    for s in snap["subjects"]:
        for r in s.get("relations", []):
            if r["peer_kind"] == "SUBJECT":
                r["peer_id"] = ren[(r.get("peer_provider", s["provider"]), r["peer_id"])]
    for s in snap["subjects"]:
        s["entity_id"] = ren[(s["provider"], s["entity_id"])]
    if snap["lineage"]["events"] or snap["bindings"]:
        pytest.skip("lineage and bindings name provider ids by design")
    renamed = run(snap)
    assert [(d["outcome"], d["identity"] and d["identity"]["canonical_model_id"]) for d in renamed] == \
        [(d["outcome"], d["identity"] and d["identity"]["canonical_model_id"]) for d in base]


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_plans_contain_only_the_shell_and_never_an_attribute(case):
    allowed = set(POLICY["writes"]["shell_columns"])
    forbidden = set(POLICY["writes"]["forbidden_attribute_fields"])

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    for d in run(case["input"]):
        if d["outcome"] != "CREATE_IDENTITY":
            assert d["write_plan"] is None and d["identity"] is None and d["creator_type"] is None
            continue
        plan = d["write_plan"]
        shell = next(o for o in plan["operations"] if o["op"] == "INSERT_IDENTITY_SHELL")
        assert set(shell["values"]) == allowed
        assert shell["values"]["identity_state"] == "DISCOVERED" and shell["values"]["enrichment_state"] == "PENDING"
        assert not (set(keys(plan["operations"])) & forbidden), "an attribute leaked into the write plan"
        assert {o["op"] for o in plan["operations"]} == set(POLICY["writes"]["operations"])
        assert plan["apply_mode"] == "PROPOSE"
        assert d["identity"]["canonical_model_id"].startswith(d["identity"]["brand_id"] + ".")


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_one_create_per_canonical_id_and_per_alias(case):
    creates = [d for d in run(case["input"]) if d["outcome"] == "CREATE_IDENTITY"]
    cids = [d["identity"]["canonical_model_id"] for d in creates]
    assert len(cids) == len(set(cids))
    aliases = [(a["provider"], a["external_id"]) for d in creates for a in d["write_plan"]["event"]["aliases"]]
    assert len(aliases) == len(set(aliases))
    taken = {i["canonical_id"] for i in case["input"]["identities"]}
    assert not (set(cids) & taken), "a plan reuses an id that already exists"


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_apply_then_redecide_converges(case):
    snap = case["input"]
    for d in run(snap):
        if d["outcome"] != "CREATE_IDENTITY":
            continue
        store = R.Store(snap["identities"], snap["bindings"])
        fin = (engine.finalize if IMPL == "engine" else R.finalize)(d, {"run_id": "r1", "created_at": "2026-10-10T00:00:00Z", "actor": "bootstrap"})
        assert store.apply(fin) == "APPLIED"
        assert store.apply(fin) == "ALREADY_APPLIED"
        assert len(store.events) == 1
        again = S.by_subject(S.run_decide(S.snapshot_after(snap, store), impl=IMPL))
        sid = f"{d['subject']['provider']}:{d['subject']['entity_id']}"
        assert again[sid]["outcome"] == "HOLD" and again[sid]["primary_reason"] == "IDENTITY_ALREADY_DISCOVERED"
        assert again[sid]["write_plan"] is None
        row = store.identities[d["identity"]["canonical_model_id"]]
        assert (row["identity_state"], row["enrichment_state"]) == ("DISCOVERED", "PENDING")


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_finalize_fills_only_the_deferred_fields(case):
    FIN = engine.finalize if IMPL == "engine" else R.finalize
    for d in run(case["input"]):
        if d["outcome"] != "CREATE_IDENTITY":
            continue
        before = copy.deepcopy(d)
        a = FIN(d, {"run_id": "r1", "created_at": "2026-10-10T00:00:00Z", "actor": "bootstrap"})
        b = FIN(d, {"run_id": "r2", "created_at": "2026-10-11T00:00:00Z", "actor": "admin:kiki"})
        assert d == before, "finalize must not mutate the decision"
        prov = lambda x: next(o for o in x["write_plan"]["operations"] if o["op"] == "INSERT_PROVENANCE")["values"]
        assert prov(d)["run_id"] is None and prov(d)["created_at"] is None and d["write_plan"]["event"]["occurred_at"] is None
        assert prov(a)["run_id"] == "r1" and a["write_plan"]["event"]["creation"]["run_id"] == "r1"
        for x in (a, b):
            x2 = copy.deepcopy(x)
            for k in ("run_id", "created_at", "actor"):
                prov(x2)[k] = None
            x2["write_plan"]["event"]["occurred_at"] = None
            x2["write_plan"]["event"]["creation"].pop("run_id")
            assert x2 == d, "finalize changed something other than the deferred fields"
        assert S.validate_decision(a) == []


@pytest.mark.parametrize("case", DECIDE, ids=IDS)
def test_first_seen_period_is_provenance_not_decision(case):
    base = run(case["input"])
    snap = copy.deepcopy(case["input"])
    for s in snap["subjects"]:
        s["first_seen_period"] = "2020-01"
    other = run(snap)
    for a, b in zip(base, other):
        assert a["fingerprints"] == b["fingerprints"] and a["outcome"] == b["outcome"]


def test_review_fingerprint_changes_when_the_question_changes():
    base = S.case_by_id("relation.sibling-revo-vs-travo")["input"]
    fp = run(base)[0]["fingerprints"]["review"]
    other = copy.deepcopy(base)
    other["subjects"][0]["relations"][0]["name_relation"] = "SUBJECT_FINER"
    assert run(other)[0]["fingerprints"]["review"] != fp
    renamed = copy.deepcopy(base)
    renamed["subjects"][0]["display_name"] = "Hilux Revo Sport"
    assert run(renamed)[0]["fingerprints"]["review"] != fp


def test_creator_type_is_admin_only_through_a_directive():
    for c in DECIDE:
        for d in run(c["input"]):
            if d["outcome"] == "CREATE_IDENTITY":
                assert (d["creator_type"] == "admin") == ("ADMIN_STRUCTURE_DECISION_APPLIED" in d["reason_codes"]), c["id"]


def test_every_create_cites_its_evidence():
    for c in DECIDE:
        for d in run(c["input"]):
            if d["outcome"] == "CREATE_IDENTITY":
                b = d["evidence_basis"]
                assert b["tier"] is not None and b["refs"] and b["kinds"], c["id"]
                prov = next(o for o in d["write_plan"]["operations"] if o["op"] == "INSERT_PROVENANCE")["values"]
                for key in ("provider", "external_id", "source_version", "first_seen_period", "reason_codes", "decision_fingerprint", "evidence_refs", "creator_type"):
                    assert prov[key], (c["id"], key)
