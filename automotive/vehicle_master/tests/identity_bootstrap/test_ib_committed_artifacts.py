"""PORTABLE invariants over the COMMITTED shadow outputs. They need neither the archived M7.0 package nor the PR #200 git objects, so they run in every CI job
(the real-data tests in test_ib_shadow.py / test_ib_market_activity.py skip when the package is absent). Nothing here re-derives a decision; it checks that the committed
files agree with each other, with the vendored PR #200 export and with the frozen milestone-3 baseline. No proprietary source data is committed for this."""
from __future__ import annotations

import collections
import csv
import json
import re
from pathlib import Path

import pytest

from identity_bootstrap.shadow import calibration, ir_rev4

SHADOW = Path(ir_rev4.__file__).parent
RESULTS = SHADOW / "results" / "2569-09_v3_M7.0"
PINNED = "1f73aee1834697cbd439291d0074293c30446e5b"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(l for l in fh if not l.startswith("#")))


@pytest.fixture(scope="module")
def ir():
    return ir_rev4.load()


@pytest.fixture(scope="module")
def dec():
    return {r["model_group_id"]: r for r in rows(RESULTS / "decisions.csv")}


@pytest.fixture(scope="module")
def base():
    return {r["model_group_id"]: r for r in rows(SHADOW / "baseline_m3" / "decisions.csv")}


@pytest.fixture(scope="module")
def summary():
    return json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def adj():
    return rows(SHADOW / "review" / "create_adjudication.csv")


def counts(d, key):
    return dict(collections.Counter(r[key] for r in d.values()))


# ---------------------------------------------------------------------------------------------------------------- the vendored PR #200 export
def test_the_export_is_pinned_and_its_content_hash_matches(ir):
    prov = ir["provenance"]
    assert prov["commit"] == PINNED == ir_rev4.PR200_COMMIT and prov["pr"] == 200 and prov["label"] == "rev4"
    assert set(prov["sources_sha256"]) == {"after_rev4.json", "before_rev3.json", "comparison.json"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in prov["sources_sha256"].values())
    assert ir_rev4.pairs_digest(ir) == prov["pairs_and_counts_sha256"], "the vendored pair data was edited"


def test_the_export_pair_maps_reconcile_with_the_relation_counts_it_reports(ir):
    for pop, pairs in (("ice_ice", ir["ice_ice_relation_pairs"]), ("ice_tdr", ir["ice_tdr_relation_pairs"])):
        got = collections.Counter(pairs.values())
        assert set(got) <= set(ir_rev4.EXPORTED_RELATIONS), pop
        for kind in ir_rev4.EXPORTED_RELATIONS:
            assert got.get(kind, 0) == ir["relation_counts"][pop].get(kind, 0), (pop, kind)
    c = ir["relation_counts"]
    assert (c["ice_ice"]["FUZZY"], c["ice_ice"]["SIBLING"], c["ice_ice"]["EQUAL_VIA_MODEL_ALIAS"]) == (7, 307, 2)
    assert (c["ice_tdr"]["FUZZY"], c["ice_tdr"]["SIBLING"], c["ice_tdr"]["EQUAL_VIA_MODEL_ALIAS"]) == (2, 55, 1)
    assert (c["before_ice_ice"]["FUZZY"], c["before_ice_ice"]["SIBLING"]) == (54, 1152) and (c["before_ice_tdr"]["FUZZY"], c["before_ice_tdr"]["SIBLING"]) == (9, 184)
    assert ir["ice_ice_relation_pairs"]["honda-honda-fit|honda-jazz"] == "EQUAL_VIA_MODEL_ALIAS"
    assert ir["ice_tdr_relation_pairs"]["honda-honda-stepwagon|honda.step_wgn"] == "EQUAL_VIA_MODEL_ALIAS"


def test_the_export_is_partial_and_the_report_says_so(ir, summary):
    """Only three relation kinds are exported: the verdicts cannot be fully verified, and every one is labelled."""
    assert set(ir_rev4.EXPORTED_RELATIONS) == {"FUZZY", "SIBLING", "EQUAL_VIA_MODEL_ALIAS"}
    status = summary["m4"]["ir_parity_status"]
    assert len(status) == 1200 and {v["status"] for v in status.values()} == {"IR_PARITY_UNRESOLVED"}
    pop = next(iter(status.values()))["population_reasons"]
    assert any(r.startswith("ice_tdr.EQUAL: stand-in 299 vs IR 239") for r in pop) and any("SUBJECT_COARSER: stand-in 46 vs IR 58" in r for r in pop)
    text = (RESULTS / "REPORT.md").read_text(encoding="utf-8")
    assert "PARTIAL parity" in text and "stand-in scenario estimate" in text and "IR_PARITY_UNRESOLVED" in text
    assert (SHADOW / "IR_FULL_PARITY_INTERFACE_REQUEST.md").exists()
    assert len(rows(RESULTS / "ir_parity_unresolved.csv")) > 0


# ---------------------------------------------------------------------------------------------------------------- decisions and transitions
def test_committed_decision_counts_are_the_reported_ones(dec):
    assert counts(dec, "A_outcome") == {"CREATE_IDENTITY": 73, "IDENTITY_REVIEW": 89, "HOLD": 1038}
    assert counts(dec, "B_outcome") == {"CREATE_IDENTITY": 72, "IDENTITY_REVIEW": 375, "HOLD": 753}
    assert len(dec) == 1200


def test_mode_b_is_a_stress_scenario_and_its_subset_relation_is_an_observation(dec, summary):
    a = {g for g, r in dec.items() if r["A_outcome"] == "CREATE_IDENTITY"}
    b = {g for g, r in dec.items() if r["B_outcome"] == "CREATE_IDENTITY"}
    assert b <= a and a - b == {"maxus-mifa-7"}, "observed on this snapshot only; NOT asserted as a law of the system"
    text = (RESULTS / "REPORT.md").read_text(encoding="utf-8")
    assert "STRESS scenario" in text and "not an upper bound" in text and "observed, not a law" in text


def test_the_transition_manifest_is_exactly_the_diff_of_the_two_committed_decision_files(dec, base):
    got = {r["model_group_id"]: r for r in rows(RESULTS / "transitions_vs_m3.csv")}
    want = {}
    for g, r in dec.items():
        old = (base[g]["A_outcome"], base[g]["A_primary"], base[g]["B_outcome"], base[g]["B_primary"])
        new = (r["A_outcome"], r["A_primary"], r["B_outcome"], r["B_primary"])
        if old != new:
            want[g] = (f"{old[0]} / {old[1]}", f"{new[0]} / {new[1]}", f"{old[2]} / {old[3]}", f"{new[2]} / {new[3]}")
    assert set(got) == set(want) and len(got) == 74
    assert all((got[g]["A_before"], got[g]["A_after"], got[g]["B_before"], got[g]["B_after"]) == want[g] for g in got)


def test_the_create_delta_against_milestone_3_is_pinned(dec, base):
    a = lambda d, k: {g for g, r in d.items() if r[k] == "CREATE_IDENTITY"}
    now, old = a(dec, "A_outcome"), a(base, "A_outcome")
    assert len(old) == 67 and len(now) == 73
    assert now - old == {"maxus-maxus-v80", "maxus-mifa-7", "mazda-mazda-mx-30", "mazda-mazda6e", "nissan-nissan-be-1", "peugeot-peugeot-5008", "volkswagen-volkswagen-t-roc", "volkswagen-vw-t-cross", "volvo-volvo-es90"}
    assert old - now == {"honda-honda-fit", "honda-honda-stepwagon", "honda-jazz"}
    for g in ("honda-jazz", "honda-honda-fit"):
        assert dec[g]["A_outcome"] == "IDENTITY_REVIEW" and "STRUCTURAL_CONFLICT" in dec[g]["A_codes"]
    assert dec["honda-honda-stepwagon"]["A_outcome"] == "HOLD" and dec["honda-honda-stepwagon"]["A_primary"] == "NOT_ACTIVATED"


def test_structural_conflict_movement_is_consistent_with_the_committed_files(dec, base, summary):
    n = lambda d, k: sum(1 for r in d.values() if "STRUCTURAL_CONFLICT" in r[k].split("|"))
    assert (n(base, "A_codes"), n(dec, "A_codes")) == (24, 9) and (n(base, "B_codes"), n(dec, "B_codes")) == (105, 48)
    s = summary["m4"]["structural"]
    assert (s["A"]["before"], s["A"]["after"], s["B"]["before"], s["B"]["after"]) == (24, 9, 105, 48)


def test_no_unsettled_id_is_a_create_and_released_groups_are_not_all_candidates(dec, summary):
    assert all(r["identity_status"] == "settled" for r in dec.values() if r["A_outcome"] == "CREATE_IDENTITY" or r["B_outcome"] == "CREATE_IDENTITY")
    rel = summary["m4"]["released_no_candidate"]
    assert rel["pr200_count"] == 177 and rel["identity_status"] == {"unmapped_name": 115, "provisional": 30, "settled": 32}
    assert len(rel["A"]["create"]) == len(rel["B"]["create"]) == 7 and set(rel["A"]["create"]) <= set(rel["settled_among_released"])


# ---------------------------------------------------------------------------------------------------------------- the provisional adjudication set
def test_the_adjudication_set_is_exactly_the_committed_mode_a_create_set_with_blank_owner_fields(adj, dec):
    assert {r["external_id"] for r in adj} == {g for g, r in dec.items() if r["A_outcome"] == "CREATE_IDENTITY"} and len(adj) == 73
    assert list(adj[0]) == calibration.COLUMNS
    assert all(r[f] == "" for r in adj for f in calibration.OWNER_FIELDS)
    first = (SHADOW / "review" / "create_adjudication.csv").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# PROVISIONAL") and "not the final truth set" in first
    assert all(r["ir_parity_status"] == "IR_PARITY_UNRESOLVED" and r["ir_parity_reasons"] for r in adj)


def test_machine_suggestions_are_never_owner_values(adj):
    sugg = [c for c in calibration.COLUMNS if c.endswith("_NON_AUTHORITATIVE")]
    assert sugg and not set(sugg) & set(calibration.OWNER_FIELDS)
    for r in adj:
        for f in calibration.OWNER_FIELDS:
            assert r[f] == ""
        assert r["machine_suggested_discovery_class_NON_AUTHORITATIVE"] in calibration.OWNER_DISCOVERY_CLASSES


# ---------------------------------------------------------------------------------------------------------------- review routing, dispatch and market activity
def test_cross_brand_candidates_are_in_mandatory_owner_review_with_their_evidence(adj):
    by = {r["external_id"]: r for r in adj}
    for g in ("maxus-mifa-7", "maxus-maxus-v80"):
        assert by[g]["mandatory_owner_review"] == "YES" and by[g]["dispatch_lane"] == "OWNER_REVIEW"
        assert "POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND" in by[g]["review_routing_flags"]
        assert "mg.mg_maxus_7" in by[g]["review_routing_evidence"] and "mg.mg_maxus_9" in by[g]["review_routing_evidence"]
    assert "mg.mg_maxus_7" in by["maxus-mifa-7"]["legacy_r6_candidate_status"]
    assert sum(1 for r in adj if r["mandatory_owner_review"] == "YES") == 2
    cb = {r["external_id"] for r in rows(RESULTS / "cross_brand_review.csv")}
    assert {"maxus-mifa-7", "maxus-maxus-v80", "maxus-mifa-9"} <= cb


def test_dispatch_manifest_never_sends_unknown_or_inactive_to_the_current_lane(adj):
    man = {r["external_id"]: r for r in rows(RESULTS / "dispatch_manifest.csv")}
    assert set(man) == {r["external_id"] for r in adj}
    mk = json.loads((RESULTS / "market_activity.json").read_text(encoding="utf-8"))
    for g, r in man.items():
        state = mk["per_group"][g]["actual"]
        assert r["activity_state"] == state
        if r["lane"] == "CURRENT_DISCOVERY":
            assert state in ("ACTIVE", "DECLINING", "REACTIVATED") and not r["review_flags"].count("POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND")
        if state == "UNKNOWN" and r["lane"] != "OWNER_REVIEW":
            assert r["lane"] == "ACTIVITY_UNCLASSIFIED"
        assert state != "INACTIVE_INFERRED", "no true zero can exist while Ice absent rows are unconfirmed"
    assert sum(1 for r in man.values() if r["lane"] == "CURRENT_DISCOVERY") == 9


def test_market_activity_keeps_absent_rows_unknown_and_states_the_completeness_assumption():
    mk = json.loads((RESULTS / "market_activity.json").read_text(encoding="utf-8"))
    assert mk["explicit_zero_rows_in_package"] == 0 and "INACTIVE_INFERRED" not in mk["actual"]["states"]
    assert mk["actual"]["states"] == {"UNKNOWN": 63, "ACTIVE": 9, "DECLINING": 1}
    assert "NOT AUTHORITATIVE" in mk["what_if_absent_is_zero"]["scenario"] and mk["what_if_absent_is_zero"]["states"].get("INACTIVE_INFERRED") == 23
    assert mk["complete_through"] == "2569-09" and "incomplete month can never supply a true zero" in mk["complete_through_assumption"]


def test_activity_age_and_volume_columns_do_not_appear_in_any_decision_file(dec):
    """The decision file carries volume for the reader, but the activity STATE/LANE columns live only in the routing outputs, never in a decision column."""
    assert not [c for c in next(iter(dec.values())) if "lane" in c or "activity" in c]
