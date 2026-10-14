"""The calibration reference evaluator (`identity_resolution/calibration/ref_eval_*.py`) agrees with the golden corpus.

The evaluator is NOT the engine (the engine gate is unchanged: `test_ir_engine_gate.py`). It is a stdlib transcription of SPEC sections 5-9 used to
say what Contract v1 would conclude on real data. This test is what stops it from drifting away from the contract: every corpus case with an
executable expectation must pass, and the independent arithmetic reference (`ir_reference.py`) must agree on windows, gates, bands and write actions.
It proves consistency with the corpus, not that the rules are right (the evaluator and the SPEC share an author).
"""
from __future__ import annotations

from collections import Counter

import pytest

import ir_reference as R
import ir_support as S
from identity_resolution.calibration import ref_eval_core as P
from identity_resolution.calibration import ref_eval_resolve as P2

REG = P.REG


def rng_ok(v, exp):
    if isinstance(exp, dict):
        if v is None:
            return False
        return ("min" not in exp or v >= exp["min"]) and ("max" not in exp or v <= exp["max"])
    return v == exp


def get_path(out, path):
    cur = {"evidence": out.get("evidence"), "comparison": out.get("comparison"), "link": {"type": out.get("link_type"), "set_id": out.get("set_id")}}
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def check_decision(fail, exp, out, label=""):
    codes = {x for x, _ in out["codes"]}
    if out["outcome"] != exp["outcome"]:
        fail(f"{label}outcome {out['outcome']} != {exp['outcome']} (primary {out.get('primary')})")
    if "proposed_status" in exp and out.get("proposed_status") != exp["proposed_status"]:
        fail(f"{label}status {out.get('proposed_status')}")
    if "method" in exp and out.get("method") != exp["method"]:
        fail(f"{label}method {out.get('method')}")
    if "link_type" in exp and out.get("link_type") != exp["link_type"]:
        fail(f"{label}link_type {out.get('link_type')} != {exp['link_type']}")
    if "policy_binding" in exp and out.get("policy_binding") != exp["policy_binding"]:
        fail(f"{label}policy_binding {out.get('policy_binding')}")
    if "primary_code" in exp and out.get("primary") != exp["primary_code"]:
        fail(f"{label}primary {out.get('primary')} != {exp['primary_code']}")
    for x in exp.get("include", []):
        if x not in codes:
            fail(f"{label}missing code {x}; have {sorted(codes)}")
    for x in exp.get("exclude", []):
        if x in codes:
            fail(f"{label}unexpected code {x}")
    if "target_ids" in exp and sorted(out.get("target_ids", [])) != sorted(exp["target_ids"]):
        fail(f"{label}targets {out.get('target_ids')} != {exp['target_ids']}")
    rv = out["review"]
    if "review_required" in exp and rv["required"] != exp["review_required"]:
        fail(f"{label}review_required {rv['required']}")
    if "review_queue" in exp and rv["queue"] != exp["review_queue"]:
        fail(f"{label}queue {rv['queue']}")
    if "review_priority" in exp and rv["priority"] != exp["review_priority"]:
        fail(f"{label}priority {rv['priority']}")
    if "writes" in exp:
        got = [(w["target_id"], w["action"], w.get("link_type")) for w in out["writes"]]
        for w in exp["writes"]:
            if not [g for g in got if g[0] == w["target_id"] and g[1] == w["action"] and ("link_type" not in w or g[2] == w["link_type"])]:
                fail(f"{label}missing write {w}; have {got}")
        if exp["writes"] == [] and got:
            fail(f"{label}expected no writes, have {got}")
    if "alternatives_min" in exp and len(out.get("alternatives", [])) < exp["alternatives_min"]:
        fail(f"{label}alternatives {len(out.get('alternatives', []))}")
    for path, e in exp.get("evidence", {}).items():
        v = get_path(out, path)
        if not rng_ok(v, e):
            fail(f"{label}evidence {path}={v!r} != {e!r}")
    prim = [x for x, r in out["codes"] if r == "primary"]
    if len(prim) != 1:
        fail(f"{label}primary count {prim}")
    for x, r in out["codes"]:
        if x not in REG:
            fail(f"{label}unknown code {x}")
        elif r not in REG[x]["roles"]:
            fail(f"{label}role {r} not allowed for {x}")
    if prim and out["outcome"] not in REG[prim[0]].get("primary_for", []):
        fail(f"{label}primary {prim[0]} not valid for {out['outcome']}")
    if out.get("link_type") == "COMPOSED_OF" and len(out.get("target_ids", [])) < 2:
        fail(f"{label}COMPOSED_OF with fewer than 2 targets")
    if out.get("link_type") in ("EQUIVALENT", "PART_OF") and len(out.get("target_ids", [])) != 1:
        fail(f"{label}{out['link_type']} must have exactly one target")
    if out["outcome"] == "AUTO" and out.get("link_type") != "EQUIVALENT":
        fail(f"{label}AUTO must be EQUIVALENT")
    sets = {}
    for w in out["writes"]:
        if w.get("set_id"):
            sets.setdefault(w["set_id"], set()).add(w["action"])
    for sid_, acts in sets.items():
        if len(acts) > 1:
            fail(f"{label}link set {sid_} has divergent write actions {acts}")


def run_case(c, fail):
    k, i, e = c["kind"], c["input"], c["expect"]
    if k == "brand_relation":
        rel, alias = P.brand_relation(i["subject_brand"], i["target_brand"], tuple(i.get("subject_brands_observed", [])))
        if rel != e["relation"]:
            fail(f"relation {rel} != {e['relation']}")
        if "alias_id" in e and alias != e["alias_id"]:
            fail(f"alias {alias} != {e['alias_id']}")
    elif k == "name_tokens":
        toks, stripped, avail = P.name_tokens(i["name"], i["brand"])
        if toks != e["tokens"] or stripped != e["prefix_stripped"] or avail != e["available"]:
            fail(f"tokens {toks} stripped {stripped} avail {avail}")
    elif k == "name_relation":
        rel, score, st, tt = P.name_relation(i["subject_name"], i["subject_brand"], i["target_name"], i["target_brand"])
        if rel != e["relation"]:
            fail(f"relation {rel} != {e['relation']} ({st} vs {tt})")
        if "score" in e and score is not None and not rng_ok(P.q(score), e["score"]):
            fail(f"score {score}")
        if "score" in e and score is None and e["score"] is not None:
            fail("score None")
    elif k == "body_relation":
        if R.body_relation(i["provider_body"], i["tdr_body_type"], P.POL) != e["body"] or P2._compat(i["provider_body"], i["tdr_body_type"]) != e["body"]:
            fail("body relation")
    elif k == "lifecycle_relation":
        rel, share = R.lifecycle_relation(i["subject_series"], i["generations"], i["as_of_period"], P.POL)
        if rel != e["lifecycle"]:
            fail(f"lifecycle {rel} != {e['lifecycle']} share {share}")
        if "share" in e and not rng_ok(share, e["share"]):
            fail(f"share {share} != {e['share']}")
        if P2._lifecycle(i["subject_series"], i["generations"], i["as_of_period"])[0] != rel:
            fail("evaluator lifecycle differs from the reference")
    elif k == "band":
        if P.band(i["dimension"], i["value"]) != e["band"] or R.band(i["dimension"], i["value"], P.POL) != e["band"]:
            fail("band")
    elif k == "series_gate":
        state, codes = R.series_gate(i, P.POL)
        if state != e["state"]:
            fail(f"state {state}")
        for x in e.get("include", []):
            if x not in codes:
                fail(f"missing {x}; have {codes}")
        for x in e.get("exclude", []):
            if x in codes:
                fail(f"unexpected {x}")
    elif k == "window":
        res = R.compare_series(i["subject_series"], i["target_series"], P.POL, i.get("max_months"), capabilities=i.get("capabilities"))
        if "refusal" in e:
            if res["refusal"] != e["refusal"]:
                fail(f"refusal {res['refusal']}")
            return
        if res["common_window"] != e["common_window"]:
            fail(f"window {res['common_window']} != {e['common_window']}")
        if res["state"] != e["series_state"]:
            fail(f"state {res['state']}")
        if "semantics_gap_months" in e and res["semantics_gap_months"] != e["semantics_gap_months"]:
            fail(f"gap {res['semantics_gap_months']} != {e['semantics_gap_months']}")
        ev, cmp_, codes = P.series_evidence(i["subject_series"], i["target_series"], i.get("max_months"))
        if ev["semantics_gap_months"] != res["semantics_gap_months"] or cmp_["common_window"] != res["common_window"] or ev["state"] != res["state"]:
            fail("evaluator window/gap/state differs from the reference")
        if sorted(cmp_["excluded_periods"], key=lambda x: x["period"]) != sorted(res["excluded"], key=lambda x: x["period"]):
            fail("evaluator excluded periods differ from the reference")
        if set(codes) != set(res["codes"]):
            fail(f"evaluator codes {sorted(codes)} vs {sorted(res['codes'])}")
        if res["stats"] and res["stats"]["ratio"] is not None and (abs(ev["ratio"] - res["stats"]["ratio"]) > 1e-9 or abs(ev["correlation"] - res["stats"]["correlation"]) > 1e-9):
            fail("evaluator statistics differ from the reference")
        for x in e.get("include", []):
            if x not in res["codes"]:
                fail(f"missing {x}; have {res['codes']}")
        for ex in e.get("excluded", []):
            if ex not in res["excluded"]:
                fail(f"missing excluded {ex}")
        for key, exp in e.get("series", {}).items():
            if not rng_ok((res["stats"] or {}).get(key), exp):
                fail(f"series.{key}")
    elif k == "protection":
        a = R.write_action(i["existing_state"], i["decision"], i["fingerprint"], P.POL)
        if a != e["action"] or P.matrix_action(i["existing_state"], i["decision"], i["fingerprint"]) != e["action"]:
            fail(f"action {a}")
    elif k == "classify":
        check_decision(fail, e, P.classify(i))
    elif k == "lineage":
        res = P.lineage(i)
        if "refusal" in e:
            if res.get("refusal") != e["refusal"]["code"]:
                fail(f"refusal {res}")
            return
        ops = res["operations"]
        for want in e.get("operations", []):
            hit = [o for o in ops if o["op"] == want["op"] and ("old_id" not in want or o["old_id"] == want["old_id"])
                   and ("new_id" not in want or o["new_id"] == want["new_id"]) and o["primary"] == want["primary_code"]]
            if not hit:
                fail(f"missing op {want['op']} {want.get('old_id')}->{want.get('new_id')} {want['primary_code']}")
                continue
            for x in want.get("include", []):
                if x not in hit[0]["codes"]:
                    fail(f"op {want['op']} missing code {x}")
            if "requires_owner_ack" in want and hit[0]["requires_owner_ack"] != want["requires_owner_ack"]:
                fail("owner ack")
            if "hint_target_ids" in want and sorted(hit[0]["hint_target_ids"]) != sorted(want["hint_target_ids"]):
                fail("hints")
            for kk, vv in want.get("affects_protected", {}).items():
                if hit[0]["affects_protected"][kk] != vv:
                    fail(f"affects {hit[0]['affects_protected']}")
        for ab in e.get("absent_operations", []):
            if any(o["op"] == ab["op"] and o["old_id"] == ab["old_id"] for o in ops):
                fail(f"unexpected op {ab}")
        if e.get("exact"):
            want = sorted((w["op"], w.get("old_id"), w.get("new_id"), w["primary_code"]) for w in e["operations"])
            got = sorted((o["op"], o["old_id"], o["new_id"], o["primary"]) for o in ops)
            if want != got:
                fail(f"exact: {got} != {want}")
    elif k == "resolve":
        res = P2.resolve(i)
        if "refusal" in e:
            if res.get("refusal") != e["refusal"]["code"]:
                fail(f"refusal {res.get('refusal')} != {e['refusal']['code']}")
            return
        if "refusal" in res:
            fail(f"unexpected refusal {res['refusal']}")
            return
        for sid, de in e["decisions"].items():
            if sid not in res["decisions"]:
                fail(f"no decision for {sid}")
                continue
            check_decision(fail, de, res["decisions"][sid], label=f"[{sid}] ")
        for want in e.get("operations", []):
            if not [o for o in res["operations"] if o["op"] == want["op"] and ("old_id" not in want or o["old_id"] == want["old_id"])
                    and ("new_id" not in want or o["new_id"] == want["new_id"]) and o["primary"] == want["primary_code"]]:
                fail(f"missing op {want}")
    # kinds with no executable expectation here (densify, claim_conflict, fingerprint) are covered by ir_reference in test_ir_corpus.py


def test_the_reference_evaluator_agrees_with_every_executable_golden_case():
    failures = []
    for case in S.cases():
        run_case(case, lambda msg, cid=case["id"]: failures.append(f"{cid}: {msg}"))
    assert not failures, f"{len(failures)} disagreement(s) with the golden corpus:\n" + "\n".join(failures[:25])


def test_the_evaluator_covers_the_kinds_the_calibration_depends_on():
    kinds = Counter(c["kind"] for c in S.cases())
    for needed in ("name_relation", "brand_relation", "window", "classify", "resolve", "lineage"):
        assert kinds[needed] > 0


def test_the_evaluator_is_a_dry_run_under_the_current_adoption_gate():
    case = next(c for c in S.cases() if c["kind"] == "resolve" and not c["expect"].get("refusal"))
    res = P2.resolve(case["input"])
    assert all(d["policy_binding"] is False for d in res["decisions"].values()), "adoption.yaml binding must stay false: every decision is advisory (I16)"
