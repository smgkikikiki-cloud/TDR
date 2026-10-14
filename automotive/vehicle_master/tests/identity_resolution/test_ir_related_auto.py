"""Rev 5 (owner decision `od_related_brand_auto_eligible`, 2026-10-12): a RELATED brand may reach AUTO -- and only behind every other AUTO gate.

What is pinned here:

  * the policy change is exactly the owner's: `ALIAS_RELATED` is AUTO-eligible, JETOUR is a separate marque typed RELATED to Chery (never SAME / RELABEL), the rev 4 baseline is archived byte for byte
    and differs from the live policy only in the keys the owner changed;
  * the behaviour change, side by side: the same candidate is PROPOSED (capped by `BRND_ALIAS_RELATED`) under the rev 4 baseline and AUTO under rev 5;
  * the safety property (SPEC I20): a RELATED brand is never identity evidence. A metamorphic test swaps the brand of EVERY classify case in the corpus from EXACT to RELATED and requires the decision
    to be unchanged (the brand relation only removes the brand cap), and named adversarial controls -- sibling model, coincident registration series, ambiguous candidates, protected identity,
    rejected pair, weak / short / fuzzy / name-less evidence -- never reach AUTO through a related brand;
  * the conditional semantics of `BRND_ALIAS_RELATED` (info while eligible, a blocking cap if a policy removes the relation from the list);
  * the measurement (`calibration/related_auto/`) is self-consistent, reproduces the committed rev 4 export, and finds no newly AUTO pair on M7.0;
  * the rev 4 evidence is still the accepted baseline: the export manifest hash is the one QA accepted, the owner sheet is blank, `adoption.binding` is false.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import ir_support as S
from identity_resolution.calibration import adapters as A
from identity_resolution.calibration import policy_baseline as PB
from identity_resolution.calibration import ref_eval_core as P
from identity_resolution.calibration import related_auto as RA
from identity_resolution.calibration import relation_export as E

PACKAGE = A.REPO_ROOT / A.PACKAGE_RELATIVE
needs_package = pytest.mark.skipif(not PACKAGE.exists(), reason="the archived M7.0 package is not in this checkout")
CASES = {c["id"]: c for c in S.cases()}
#: The export manifest hash the rev 4 QA accepted (typed here on purpose: the baseline must not move).
ACCEPTED_REV4_EXPORT_MANIFEST_SHA256 = "e9d74e05ce9c09ad59bad2654d16fbb74e06969e929b7415b5e55a0fc2d2e0b8"


def decide(case_id: str, baseline: bool = False) -> dict:
    inp = CASES[case_id]["input"]
    if baseline:
        with PB.rev4_baseline():
            return P.classify(copy.deepcopy(inp))
    return P.classify(copy.deepcopy(inp))


def codes(out: dict, role: str | None = None) -> set:
    return {c for c, r in out["codes"] if role is None or r == role}


def swap_brand(inp: dict, relation: str, alias_id: str | None) -> dict:
    out = copy.deepcopy(inp)
    for cand in out["candidates"]:
        cand["evidence"]["brand"] = {"relation": relation, "subject_key": "k", "target_key": "k", "alias_id": alias_id}
    return out


def key(out: dict) -> tuple:
    return (out["outcome"], out.get("primary"), tuple(sorted(out.get("target_ids", []))), out.get("link_type"), out.get("proposed_status"), out["review"]["queue"], out["review"]["required"],
            tuple(sorted((w["target_id"], w["action"]) for w in out["writes"])))


# ---------------------------------------------------------------------------------------------------------------------------------------- the policy change is exactly the owner's
def test_policy_is_rev_5_related_is_auto_eligible_and_binding_is_false():
    pol, adoption = S.policy(), S.adoption()
    assert pol["policy"]["revision"] == 5 and pol["policy"]["status"] == "draft_not_frozen" and adoption["binding"] is False
    cand = pol["candidates"]
    assert cand["brand_relations_auto_eligible"] == ["EXACT", "ALIAS_SAME", "ALIAS_RELABEL", "ALIAS_RELATED"] and "ALIAS_RELATED" in cand["brand_relations_allowed"]
    assert pol["provenance"]["candidates.brand_relations_auto_eligible"] == "proposal", "the list stays a draft proposal; only the owner's decision about RELATED is recorded"
    decisions = {d["id"]: d for d in adoption["owner_decisions"]}
    for name in ("od_relation_first_producer_pool", "od_catalog_brand_alias_not_a_relation", "od_related_brand_auto_eligible"):
        assert decisions[name]["status"] == "accepted" and decisions[name]["decided_on"] == "2026-10-12", name
    assert "never implies same-model identity" in decisions["od_related_brand_auto_eligible"]["decision"]
    entries = {e["id"]: e for e in adoption["entries"]}
    assert entries["candidates_pool_rules"]["status"] == "pending", "the owner decided the RELATED part only; the pool rules stay pending"
    standing = {"od_ice_absent_row_unknown", "od_tdr_absent_row_traced", "od_binding_false", "od_not_frozen"}
    assert all(decisions[n]["status"] == "standing" for n in standing)


def test_jetour_is_a_separate_marque_typed_related_to_chery():
    classes = {a["id"]: a for a in S.policy()["aliases"]["brand"]}
    assert classes["chery_jetour"]["relation"] == "RELATED" and S.policy()["alias_provenance"]["chery_jetour"] == "owner_seed"
    for a in classes.values():
        if a["relation"] in ("SAME", "RELABEL"):
            assert not {P.compact(m) for m in a["members"]} & {"jetour", "chery"}, f"{a['id']}: JETOUR/Chery must never be SAME or RELABEL"
    assert P.brand_relation("JETOUR", "Chery") == ("ALIAS_RELATED", "chery_jetour") and P.brand_relation("Chery", "Jetour") == ("ALIAS_RELATED", "chery_jetour")
    assert P.brand_relation("JETOUR", "JETOUR")[0] == "EXACT" and P.brand_relation("OMODA", "Chery")[0] == "MISMATCH", "the class names two marques only"


def test_the_rev_4_baseline_is_archived_byte_for_byte_and_differs_only_where_the_owner_changed_it():
    manifest = json.loads((E.OUT / "MANIFEST.json").read_text(encoding="utf-8"))
    pins = manifest["sources"]["evaluator_and_contract"]
    assert hashlib.sha256(PB.REV4_POLICY.read_bytes()).hexdigest() == pins["automotive/vehicle_master/identity_resolution/contract/v1/policy.yaml"]
    assert hashlib.sha256(PB.REV4_EVALUATOR.read_bytes()).hexdigest() == pins["automotive/vehicle_master/identity_resolution/calibration/ref_eval_core.py"]
    assert PB.delta(S.policy(), PB.rev4_policy()) == set(PB.EXPECTED_DELTA)
    base = PB.rev4_policy()
    assert base["policy"]["revision"] == 4 and base["candidates"]["brand_relations_auto_eligible"] == ["EXACT", "ALIAS_SAME", "ALIAS_RELABEL"]
    assert "chery_jetour" not in {a["id"] for a in base["aliases"]["brand"]}
    # the live evaluator differs from the archived one only by the audit-info line
    live, old = Path(P.__file__).read_text(encoding="utf-8").splitlines(), PB.REV4_EVALUATOR.read_text(encoding="utf-8").splitlines()
    added = [l for l in live if l not in old]
    removed = [l for l in old if l not in live]
    assert not removed and all("ALIAS_RELATED" in l or "rev 5" in l for l in added), added


def test_the_baseline_context_restores_the_live_policy_and_brand_tables():
    before = (copy.deepcopy(P.POL), dict(P.BRAND_CLASS), list(P.RELATED))
    with PB.rev4_baseline() as base:
        assert P.POL["policy"]["revision"] == 4 and P.brand_relation("JETOUR", "Chery")[0] == "MISMATCH"
        assert base["candidates"]["brand_relations_auto_eligible"] == P.POL["candidates"]["brand_relations_auto_eligible"]
    assert (P.POL, dict(P.BRAND_CLASS), list(P.RELATED)) == before and P.POL["policy"]["revision"] == 5


def test_an_unexpected_policy_drift_refuses_to_build_a_baseline(monkeypatch):
    original = P.POL["series"]["strong"]["correlation_min"]
    P.POL["series"]["strong"]["correlation_min"] = 0.5
    try:
        with pytest.raises(RuntimeError, match="unexpected keys"):
            with PB.rev4_baseline():
                pass
    finally:
        P.POL["series"]["strong"]["correlation_min"] = original


# ---------------------------------------------------------------------------------------------------------------------------------------- behaviour change, side by side
def test_the_same_related_candidate_is_capped_under_rev_4_and_auto_under_rev_5():
    cid = "classify.related-brand-auto-when-every-gate-passes"
    new, old = decide(cid), decide(cid, baseline=True)
    assert new["outcome"] == "AUTO" and new["primary"] == "AUTO_ALL_GATES_PASSED" and new["link_type"] == "EQUIVALENT" and new["review"]["required"] is False
    assert ("BRND_ALIAS_RELATED", "info") in new["codes"] and "BRND_ALIAS_RELATED" not in codes(new, "blocking")
    assert new["evidence"]["brand"]["relation"] == "ALIAS_RELATED" and new["evidence"]["brand"]["alias_id"], "the decision record keeps the relation and its alias provenance"
    assert old["outcome"] == "PROPOSE" and old["primary"] == "PROPOSE_SERIES_STRONG_CAPPED" and ("BRND_ALIAS_RELATED", "blocking") in old["codes"]


def test_a_policy_that_removes_the_relation_restores_the_blocking_cap():
    cid = "classify.related-brand-auto-when-every-gate-passes"
    original = list(P.POL["candidates"]["brand_relations_auto_eligible"])
    P.POL["candidates"]["brand_relations_auto_eligible"] = [r for r in original if r != "ALIAS_RELATED"]
    try:
        out = decide(cid)
    finally:
        P.POL["candidates"]["brand_relations_auto_eligible"] = original
    assert out["outcome"] == "PROPOSE" and ("BRND_ALIAS_RELATED", "blocking") in out["codes"] and ("BRND_ALIAS_RELATED", "info") not in out["codes"]


def test_reason_code_semantics_say_info_while_eligible_and_a_cap_otherwise():
    spec = S.registry()["codes"]["BRND_ALIAS_RELATED"]
    assert set(spec["roles"]) == {"blocking", "info"} and spec["effect"] == "cap_proposed"
    assert "candidates.brand_relations_auto_eligible" in spec["summary"] and "Rev 5" in spec["summary"]
    text = S.spec_text()
    assert "**Rev 5 (owner decision `od_related_brand_auto_eligible`, 2026-10-12): `ALIAS_RELATED` is on that list.**" in text and "**I20 — A brand relation is never identity evidence.**" in text
    assert text.index("**I19 —") < text.index("**I20 —")
    ids = {e["id"] for e in S.taxonomy()["entries"]}
    assert {"BRND-08", "BRND-09"} <= ids


# ---------------------------------------------------------------------------------------------------------------------------------------- the safety property (SPEC I20)
def test_swapping_an_equal_brand_for_a_related_brand_changes_nothing_but_the_audit_code_across_the_whole_corpus():
    checked = 0
    for cid, case in CASES.items():
        if case["kind"] != "classify" or cid.startswith("classify.related-brand"):
            continue
        cands = case["input"]["candidates"]
        if not cands or any(c["evidence"]["brand"]["relation"] != "EXACT" for c in cands):
            continue
        base = P.classify(copy.deepcopy(case["input"]))
        swapped = P.classify(swap_brand(case["input"], "ALIAS_RELATED", "mercedes_amg_maybach"))
        assert key(base) == key(swapped), f"{cid}: a related brand moved the decision {key(base)} -> {key(swapped)}"
        assert codes(swapped) - codes(base) <= {"BRND_ALIAS_RELATED"} and codes(base) - codes(swapped) <= {"BRND_EXACT"}, cid
        checked += 1
    assert checked >= 80, checked   # 88 at the time of writing: every classify case whose candidates all carry an EXACT brand


def test_swapping_a_related_brand_for_an_unrelated_one_still_removes_the_candidate():
    """The other direction of the same property: a MISMATCH brand is not a candidate at all, related or not (resolved by the pool rules, not by the AUTO gate)."""
    assert "ALIAS_RELATED" in S.policy()["candidates"]["brand_relations_allowed"] and "MISMATCH" not in S.policy()["candidates"]["brand_relations_allowed"]
    assert P.brand_relation("MERCEDES AMG", "Toyota")[0] == "MISMATCH" and P.brand_relation("JETOUR", "Toyota")[0] == "MISMATCH"


ADVERSARIAL_TWINS = {
    "sibling nameplate": ("classify.related-brand-twin-veto-sibling", "NO_CANDIDATE"),
    "contradicting name with a perfect series (a coincident series)": ("classify.related-brand-twin-veto-contradiction", "NO_CANDIDATE"),
    "ambiguous within margin": ("classify.related-brand-twin-ambiguous-within-margin", "AMBIGUOUS"),
    "target held by an APPROVED / LOCKED claim elsewhere": ("classify.related-brand-twin-claim-conflict-protected-target", "STRUCTURAL_REVIEW"),
    "weak fit to a protected target": ("classify.related-brand-twin-protected-target-excluded-when-weak", "NO_CANDIDATE"),
    "rejected pair, evidence changed": ("classify.related-brand-twin-rejected-reopened-never-auto", "PROPOSE"),
    "rejected pair, evidence unchanged": ("classify.related-brand-twin-rejected-suppressed", None),
    "typo-tolerant name": ("classify.related-brand-twin-capped-fuzzy-name", "PROPOSE"),
    "subject is a coarser name": ("classify.related-brand-twin-capped-name-subject-coarser", "PROPOSE"),
    "subject is a finer name": ("classify.related-brand-twin-capped-name-subject-finer", "PROPOSE"),
    "overlap below the AUTO minimum": ("classify.related-brand-twin-capped-overlap-below-auto", "PROPOSE"),
    "volume below the AUTO minimum": ("classify.related-brand-twin-capped-volume-below-auto", "PROPOSE"),
    "body mismatch": ("classify.related-brand-twin-capped-body-mismatch", "PROPOSE"),
    "partial lifecycle": ("classify.related-brand-twin-capped-lifecycle-partial", "PROPOSE"),
    "unverified target": ("classify.related-brand-twin-capped-target-unverified", "PROPOSE"),
    "provisional subject": ("classify.related-brand-twin-capped-provisional-subject", "PROPOSE"),
    "raw-name subject": ("classify.related-brand-twin-capped-unmapped-name-subject", "PROPOSE"),
    "quarantined evidence": ("classify.related-brand-twin-capped-quarantined", "PROPOSE"),
    "name only, series not strong": ("classify.related-brand-twin-name-only-never-auto", "PROPOSE"),
    "equal name, weak series": ("classify.related-brand-twin-name-equal-weak-series", "PROPOSE"),
    "no name, strong series": ("classify.related-brand-twin-name-unavailable-strong-series", "PROPOSE"),
    "monthly-fit failure": ("classify.related-brand-twin-monthly-fit-fail-surfaces", "PROPOSE"),
    "lifecycle disjoint": ("classify.related-brand-twin-veto-lifecycle-disjoint", "NO_CANDIDATE"),
    "series decisively wrong": ("classify.related-brand-twin-veto-series-decisively-wrong", "NO_CANDIDATE"),
}


@pytest.mark.parametrize("label", sorted(ADVERSARIAL_TWINS))
def test_a_related_brand_never_makes_these_cases_auto(label):
    cid, expected = ADVERSARIAL_TWINS[label]
    out = P.classify(copy.deepcopy(CASES[cid]["input"]))
    assert all(c["evidence"]["brand"]["relation"] == "ALIAS_RELATED" for c in CASES[cid]["input"]["candidates"]), cid
    assert out["outcome"] != "AUTO" and not any(w["action"] in ("INSERT_AUTO", "PROMOTE_TO_AUTO", "KEEP_AUTO") for w in out["writes"]), f"{label}: {out['outcome']}"
    if expected:
        assert out["outcome"] == expected, (label, out["outcome"])
    assert key(out) == key(P.classify(swap_brand(CASES[cid]["input"], "EXACT", None))), f"{label}: not the same decision as under an equal brand"


def test_the_resolve_level_controls_a_related_brand_is_not_a_different_model():
    for cid, outcome, primary in (("resolve.brand-related-coincident-series-different-model", "NO_CANDIDATE", "NO_CANDIDATE_ALL_EXCLUDED"),
                                  ("resolve.jetour-affiliation-does-not-make-a-different-model-auto", "NO_CANDIDATE", "NO_CANDIDATE_ALL_EXCLUDED")):
        out = list(__import__("identity_resolution.calibration.ref_eval_resolve", fromlist=["resolve"]).resolve(copy.deepcopy(CASES[cid]["input"]))["decisions"].values())[0]
        assert (out["outcome"], out["primary"]) == (outcome, primary), cid
        assert "NAME_CONTRADICTION" in codes(out)


def test_the_resolve_level_positives_a_genuinely_equivalent_cross_brand_vehicle_is_auto():
    from identity_resolution.calibration import ref_eval_resolve as R
    for cid in ("resolve.brand-related-amg-auto", "resolve.mg-registered-maxus-related-auto", "resolve.jetour-equal-model-under-chery-auto"):
        out = list(R.resolve(copy.deepcopy(CASES[cid]["input"]))["decisions"].values())[0]
        assert out["outcome"] == "AUTO" and out["primary"] == "AUTO_ALL_GATES_PASSED", cid
        assert out["evidence"]["brand"]["relation"] == "ALIAS_RELATED" and ("BRND_ALIAS_RELATED", "info") in out["codes"], cid
        # and the same input is capped under the rev 4 baseline
        with PB.rev4_baseline():
            old = list(R.resolve(copy.deepcopy(CASES[cid]["input"]))["decisions"].values())[0]
        assert old["outcome"] != "AUTO", f"{cid}: rev 4 baseline must not reach AUTO"


def test_the_two_resolve_cases_that_changed_id_keep_a_trace_of_what_they_replace():
    assert "classify.capped-related-brand" not in CASES and "resolve.brand-related-amg-caps" not in CASES and "resolve.mg-registered-maxus-related" not in CASES
    assert "rev 4" in CASES["resolve.brand-related-amg-auto"]["note"] and "rev 4" in CASES["classify.related-brand-auto-when-every-gate-passes"]["note"]
    assert sum(1 for c in CASES.values() if c["id"].startswith("classify.related-brand-twin-")) == len(ADVERSARIAL_TWINS)


# ---------------------------------------------------------------------------------------------------------------------------------------- the measurement
def impact() -> dict:
    return json.loads((RA.OUT / "impact.json").read_text(encoding="utf-8"))


def test_the_impact_measurement_is_self_consistent_and_agrees_with_the_committed_rev_4_export():
    assert RA.verify() == []
    m = impact()
    assert m["contract"] == {"baseline_revision": 4, "live_revision": 5, "binding": False}
    assert m["baseline_cross_check"]["mismatches"] == [] and m["baseline_cross_check"]["subjects_compared"] == m["subjects"] == 1200
    assert m["baseline_cross_check"]["export_manifest_sha256"] == hashlib.sha256((E.OUT / "MANIFEST.json").read_bytes()).hexdigest() == ACCEPTED_REV4_EXPORT_MANIFEST_SHA256
    assert sum(m["outcomes"]["rev4"].values()) == sum(m["outcomes"]["rev5"].values()) == 1200
    assert m["outcomes"]["rev4"]["AUTO"] == 69, "the rev 4 AUTO count the QA accepted"


def test_the_measured_behaviour_change_on_m7_0_is_small_and_creates_no_auto_pair():
    m = impact()
    assert [(c["group"], c["rev4_outcome"], c["rev5_outcome"]) for c in m["changed_decisions"]] == [("JETOUR|ไม่ระบุ", "NO_CANDIDATE", "INSUFFICIENT_DATA")]
    fx = m["false_auto_exposure"]
    assert fx["newly_auto_groups"] == [] and fx["newly_auto_eligible_pairs"] == [] and fx["auto_groups_rev4"] == fx["auto_groups_rev5"] == 69 and fx["owner_labels_on_these_pairs"] == 0
    assert fx["assumption_provenance_classes_now_auto_capable"] == sorted(c for c, v in S.policy()["alias_provenance"].items() if v == "assumption" and c in {a["id"] for a in S.policy()["aliases"]["brand"] if a["relation"] == "RELATED"})
    rp = m["related_pairs"]
    assert rp["count"] == sum(rp["first_gate_funnel"].values()) == sum(rp["by_alias_class"].values()) and rp["auto_eligible_rev5"] == 0
    rows = (RA.OUT / "related_pairs.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) - 1 == rp["count"]
    changed = (RA.OUT / "changed_decisions.csv").read_text(encoding="utf-8").splitlines()
    assert len(changed) - 1 == len(m["changed_decisions"])


def test_the_report_states_the_exposure_and_the_baseline_preservation():
    text = (RA.OUT / "RELATED_AUTO_IMPACT.md").read_text(encoding="utf-8")
    for must in ("Decisions that changed: **1** of 1200", "AUTO groups: **69 → 69**", "False-AUTO exposure on the real data: 0 newly AUTO-eligible pairs", "Nothing from rev 4 is rewritten",
                 "the owner's to confirm", "binding: false"):
        assert must in text, must


@needs_package
def test_the_impact_measurement_regenerates_byte_for_byte_from_the_archived_package():
    fresh = RA.build_files(RA.measure(A.load_ice_package(), A.load_extracts()))
    for name, data in fresh.items():
        assert (RA.OUT / name).read_bytes() == data, name


# ---------------------------------------------------------------------------------------------------------------------------------------- the rev 4 evidence is untouched
def test_the_rev_4_evidence_and_the_owner_sheet_are_untouched_and_blank():
    assert hashlib.sha256((E.OUT / "MANIFEST.json").read_bytes()).hexdigest() == ACCEPTED_REV4_EXPORT_MANIFEST_SHA256
    pairs = sum(len((E.OUT / E.FILES[k]).read_bytes().splitlines()) for k in ("pairs_ice_ice", "pairs_ice_tdr"))
    assert pairs == 26505 + 12412 == 38917
    sheet = (A.CALIBRATION_DIR / "r6_owner_review.csv").read_text(encoding="utf-8-sig").splitlines()
    import csv, io
    rows = list(csv.DictReader(io.StringIO("\n".join(sheet))))
    assert len(rows) == 560 and all(not r["owner_verdict"] and not r["owner_link_type"] and not r["owner_canonical_model_id"] and not r["owner_notes"] for r in rows)
    pack = json.loads((A.CALIBRATION_DIR / "owner_decision_pack" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert pack["export_manifest_sha256"] == ACCEPTED_REV4_EXPORT_MANIFEST_SHA256 and pack["binding"] is False
