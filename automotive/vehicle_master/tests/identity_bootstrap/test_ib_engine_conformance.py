"""The engine (identity_bootstrap/engine) and the independent test oracle (ib_reference.py) must agree exactly, everywhere we can check."""
from __future__ import annotations

import copy
import random

import pytest

import ib_reference as R
import ib_support as S
from identity_bootstrap import engine

POLICY, REGISTRY = S.policy(), S.registry()
DECIDE = S.kind("decide")


def both(snapshot, policy=None):
    policy = policy or POLICY
    outs = []
    for fn in (R.decide, engine.decide):
        try:
            outs.append(fn(copy.deepcopy(snapshot), policy, REGISTRY))
        except (R.Refusal, engine.Refusal) as r:
            outs.append(("REFUSAL", r.code))
    return outs


@pytest.mark.parametrize("case", DECIDE, ids=[c["id"] for c in DECIDE])
def test_engine_equals_oracle_on_every_corpus_snapshot(case):
    oracle, eng = both(case["input"])
    assert oracle == eng


def test_engine_equals_oracle_under_shuffles_and_unit_changes():
    for case in DECIDE:
        for seed in range(3):
            rnd = random.Random(seed)
            snap = copy.deepcopy(case["input"])
            for key in ("subjects", "identities", "bindings"):
                rnd.shuffle(snap[key])
            for s in snap["subjects"]:
                rnd.shuffle(s.get("relations", []))
                s["units"] = rnd.choice([0, 3, 499, 10_000_000])
            oracle, eng = both(snap)
            assert oracle == eng, case["id"]


def test_engine_equals_oracle_under_every_policy_mutation():
    from test_ib_policy_mutation import MUTATIONS, mutate
    for path, value in MUTATIONS.items():
        pol = mutate(path, value)
        for case in DECIDE:
            try:
                oracle, eng = both(case["input"], pol)
            except Exception as exc:       # a mutation may make the policy unusable; both must then fail the same way
                pytest.fail(f"{path}: {exc!r}")
            assert oracle == eng, f"{path} / {case['id']}"


def test_engine_finalize_equals_oracle_finalize():
    inv = {"run_id": "r1", "created_at": "2026-10-10T00:00:00Z", "actor": "bootstrap"}
    for case in DECIDE:
        if "refusal" in case["expect"]:
            continue
        for d in engine.decide(copy.deepcopy(case["input"]), POLICY, REGISTRY):
            if d["write_plan"]:
                assert engine.finalize(d, inv) == R.finalize(d, inv)


def test_engine_is_a_pure_function_of_its_inputs():
    case = S.case_by_id("batch.two-providers-one-identity")
    a = engine.decide(copy.deepcopy(case["input"]), POLICY, REGISTRY)
    b = engine.decide(copy.deepcopy(case["input"]), POLICY, REGISTRY)
    assert a == b
    snap = copy.deepcopy(case["input"])
    engine.decide(snap, POLICY, REGISTRY)
    assert snap == case["input"], "the engine must not mutate its input"
    pol = copy.deepcopy(POLICY)
    engine.decide(copy.deepcopy(case["input"]), pol, REGISTRY)
    assert pol == POLICY


def test_engine_never_executes_a_write():
    """There is no writer in the package and the engine returns plain data: a plan is a dict, never a callable or a connection."""
    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)
        else:
            yield node
    for case in DECIDE:
        if "refusal" in case["expect"]:
            continue
        for d in engine.decide(copy.deepcopy(case["input"]), POLICY, REGISTRY):
            assert all(isinstance(x, (str, int, float, bool, type(None))) for x in walk(d))
