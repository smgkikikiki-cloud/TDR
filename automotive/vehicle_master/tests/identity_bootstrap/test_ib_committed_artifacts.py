"""PORTABLE invariants over the COMMITTED shadow outputs. They need neither the archived M7.0 package nor the PR #200 git objects, so they run in every CI job
(the real-data tests in test_ib_shadow.py / test_ib_market_activity.py skip when the package is absent). Nothing here re-derives a decision; it checks that the committed
files agree with each other, with the vendored, hash-pinned PR #200 relation export and with the frozen b132a86 baseline. No proprietary source data is committed for this."""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

import pytest

from identity_bootstrap.shadow import calibration, ir_export

SHADOW = Path(ir_export.__file__).parent
RESULTS = SHADOW / "results" / "2569-09_v3_M7.0"
BASE = SHADOW / "baseline_b132a86"
ADDED = {"audi-audi-a8l", "audi-audi-s3", "bmw-x2", "byd-e6", "isuzu-isuzu-cab4", "jaecoo-jaecoo-j5", "jaecoo-jaecoo-j7", "volkswagen-volkswagen-multivan", "volkswagen-vw-idbuzz", "wuling-binguo"}
OWNER_REVIEW = {"audi-audi-a8l", "audi-audi-s3", "byd-e6", "isuzu-isuzu-cab4", "jaecoo-jaecoo-j5", "jaecoo-jaecoo-j7", "maxus-maxus-v80", "volkswagen-volkswagen-multivan", "volkswagen-vw-idbuzz", "wuling-binguo"}


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(l for l in fh if not l.startswith("#")))


@pytest.fixture(scope="module")
def export():
    return ir_export.load()


@pytest.fixture(scope="module")
def dec():
    return {r["model_group_id"]: r for r in rows(RESULTS / "decisions.csv")}


@pytest.fixture(scope="module")
def base():
    return {r["model_group_id"]: r for r in rows(BASE / "decisions.csv")}


@pytest.fixture(scope="module")
def summary():
    return json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def adj():
    return rows(SHADOW / "review" / "create_adjudication.csv")


def counts(d, key):
    return dict(collections.Counter(r[key] for r in d.values()))


# ---------------------------------------------------------------------------------------------------------------- the pinned export and the report's claims
def test_the_report_names_the_exact_producer_pin(summary):
    pr = summary["m5"]["pr200"]
    assert pr["commit"] == "eed76aa6ad6380afea60d604e5e7eac87abedb06" and pr["export_id"] == "ir-rev4-m7.0-relations/1" and pr["manifest_sha256"] == ir_export.PIN_MANIFEST_SHA256
    assert pr["schema_version"] == "ir-relation-export/1" and pr["contract"]["adoption_binding"] is False and pr["contract"]["status"] == "draft_not_frozen"
    assert {k: v["sha256"] for k, v in pr["files"].items()} == {k: v["sha256"] for k, v in ir_export.load().manifest["files"].items()}


def test_every_relation_in_the_committed_decisions_traces_to_the_export(summary, export):
    par = summary["m5"]["parity"]["lexical_relations"]
    assert par["snapshot_relations_wrong"] == []
    for pop, n in (("ice_ice", 26505), ("ice_tdr", 12412)):
        assert par[pop]["evaluated_pairs"] == par[pop]["pairs_read_by_the_shadow"] == n and par[pop]["all_pairs_read"] is True
        assert par[pop]["counts_equal_manifest_for_all_nine_kinds"] is True
        assert par[pop]["snapshot_relations_not_in_export_or_relabelled"] == [] and par[pop]["export_relations_not_passed_on"] == []
    passed = {k: sum(1 for r in rows_.values() if r["r"] not in ("CONTRADICTION", "UNAVAILABLE")) for k, rows_ in (("ice_ice", export.ice_ice), ("ice_tdr", export.ice_tdr))}
    assert (par["ice_ice"]["relations_passed_to_bootstrap"], par["ice_tdr"]["relations_passed_to_bootstrap"]) == (passed["ice_ice"], passed["ice_tdr"]) == (439, 391)


def test_candidate_pool_parity_and_the_unresolved_subjects_are_reported_with_exact_reasons(summary):
    pp = summary["m5"]["parity"]["candidate_pools"]
    assert pp["shadow_candidates_outside_pool"] == [] and pp["pool_members_not_read"] == [] and pp["subjects_with_empty_pool"] == 226
    assert pp["old_vs_pool_by_kind"] == {"BRAND_NOT_ALLOWED_IN_POOL": 1, "POOL_WITHOUT_RESOLVED_BRAND": 7}
    sub = summary["m5"]["parity"]["subjects"]
    assert (sub["resolved"], sub["unresolved"]) == (1192, 8)
    ids = set(sub["unresolved_ids_and_reasons"])
    assert ids == {"JETOUR|ไม่ระบุ", "MERCEDES AMG|SL 43", "MERCEDES AMG|SL 55 4MATIC", "MERCEDESBENZ MAYBACH|S680 4 M", "RANGE ROVER|AUTOBIOGRAPHY P400E LWB", "RANGE ROVER|EVOQUE 2 2 SD4 DYNAMIC", "RANGE ROVER|EVOQUE 2 2L SD4", "maxus-maxus-epc1a"}
    assert all(all(x.startswith("BRAND_RESOLUTION_VS_POOL") for x in r) for r in sub["unresolved_ids_and_reasons"].values())
    listed = {r["external_id"] for r in rows(RESULTS / "parity_unresolved.csv")}
    assert listed == ids


def test_the_tdr_universe_binding_and_the_eight_unresolved_subjects_are_in_the_report(summary):
    b = summary["m5"]["parity"]["tdr_universe_binding"]
    assert (b["models"], b["models_with_aliases"], b["alias_strings"], b["brands"]) == (323, 296, 662, 62) and b["statuses"] == {"CURRENT": 318, "HISTORICAL": 5}
    assert b["tdr_inputs_sha256"] == {n: ir_export.load().manifest["sources"]["tdr_inputs"][n] for n in ir_export.TDR_INPUT_FILES}
    sub = summary["m5"]["parity"]["subjects"]
    assert (sub["resolved"], sub["unresolved"]) == (1192, 8)


def test_the_committed_catalog_aliases_used_for_routing_equal_the_bound_snapshot(adj):
    """The nine OWNER_REVIEW alias cases read these aliases; they must come from the hash-bound snapshot, not a drifting catalog."""
    from identity_bootstrap.shadow import run as shadow_run, tdr_catalog
    export = ir_export.load()
    cat = tdr_catalog.load(shadow_run.DEFAULT_MODELS, shadow_run.DEFAULT_LEGACY, True)
    ir_export.verify_universe(export, rows(RESULTS / "decisions.csv"), cat)
    for r in adj:
        if "POSSIBLE_EXISTING_IDENTITY_CATALOG_ALIAS" in r["review_routing_flags"]:
            for part in r["review_routing_evidence"].split("TDR_CATALOG_ALIAS_EQUALS_PROVIDER_NAME(")[1:]:
                cid = part.split("existing_identity=")[1].split(",")[0]
                alias = part.split("alias=")[1].split(",")[0]
                assert alias.casefold() in [a.casefold() for a in export.tdr_models[cid]["aliases"]], (r["external_id"], cid, alias)


def test_dry_run_vs_bootstrap_is_reported_separately(summary):
    dr = summary["m5"]["dry_run_vs_bootstrap"]
    assert dr["cross_tab"]["IR NO_CANDIDATE -> Bootstrap CREATE_IDENTITY"] == 82 and dr["cross_tab"]["IR AUTO -> Bootstrap HOLD"] == 69
    assert not any(k.endswith("CREATE_IDENTITY") and not k.startswith("IR NO_CANDIDATE") for k in dr["cross_tab"]), "no CREATE where the reference evaluator found a candidate"
    assert [x["id"] for x in dr["divergent"]] == ["audi-audi-a1"]
    assert [r["external_id"] for r in rows(RESULTS / "dry_run_vs_bootstrap.csv")] == ["audi-audi-a1"]


# ---------------------------------------------------------------------------------------------------------------- decisions and transitions
def test_committed_decision_counts_are_the_reported_ones(dec, base):
    assert len(dec) == 1200 and len(base) == 1200 and set(dec) == set(base) == set(ir_export.load().subjects)
    assert counts(base, "A_outcome") == {"CREATE_IDENTITY": 73, "IDENTITY_REVIEW": 89, "HOLD": 1038} and counts(base, "B_outcome") == {"CREATE_IDENTITY": 72, "IDENTITY_REVIEW": 375, "HOLD": 753}
    assert counts(dec, "A_outcome") == {"CREATE_IDENTITY": 82, "IDENTITY_REVIEW": 127, "HOLD": 991}
    assert counts(dec, "B_outcome") == {"CREATE_IDENTITY": 82, "IDENTITY_REVIEW": 365, "HOLD": 753}


def test_mode_b_is_a_stress_scenario_and_equality_with_mode_a_is_an_observation(dec):
    a = {g for g, r in dec.items() if r["A_outcome"] == "CREATE_IDENTITY"}
    b = {g for g, r in dec.items() if r["B_outcome"] == "CREATE_IDENTITY"}
    assert a == b, "observed on this snapshot only; NOT asserted as a law of the system"
    text = (RESULTS / "REPORT.md").read_text(encoding="utf-8")
    assert "STRESS scenario" in text and "not an upper bound" in text


def test_the_transition_manifest_is_exactly_the_diff_of_the_two_committed_decision_files(dec, base):
    got = {r["model_group_id"]: r for r in rows(RESULTS / "transitions_vs_b132a86.csv")}
    want = set()
    for g, r in dec.items():
        b = base[g]
        if (b["A_outcome"], b["A_primary"], b["A_codes"], b["B_outcome"], b["B_primary"], b["B_codes"]) != (r["A_outcome"], r["A_primary"], r["A_codes"], r["B_outcome"], r["B_primary"], r["B_codes"]):
            want.add(g)
    assert set(got) == want and len(got) == 77
    for g, t in got.items():
        assert t["A_before"] == f"{base[g]['A_outcome']} / {base[g]['A_primary']}" and t["A_after"] == f"{dec[g]['A_outcome']} / {dec[g]['A_primary']}"
        assert t["B_before"] == f"{base[g]['B_outcome']} / {base[g]['B_primary']}" and t["B_after"] == f"{dec[g]['B_outcome']} / {dec[g]['B_primary']}"
        assert t["relation_changes"] and t["ir_dry_run_outcome"] and t["tdr_candidate_ids_involved"] is not None


def test_every_changed_create_has_its_relation_evidence_and_tdr_ids_in_the_manifest():
    got = {r["model_group_id"]: r for r in rows(RESULTS / "transitions_vs_b132a86.csv")}
    for g in ADDED:
        t = got[g]
        assert t["A_after"].startswith("CREATE_IDENTITY") and not t["A_before"].startswith("CREATE_IDENTITY")
    for g in ADDED - {"bmw-x2"}:
        assert got[g]["tdr_candidate_ids_involved"] and "EQUAL -> none" in got[g]["relation_changes"], g
    assert got["bmw-x2"]["tdr_candidate_ids_involved"] == "bmw.ix2" and "SUBJECT_COARSER -> none" in got["bmw-x2"]["relation_changes"]
    m = got["maxus-mifa-7"]
    assert m["A_before"].startswith("CREATE_IDENTITY") and m["A_after"] == "IDENTITY_REVIEW / STRUCTURAL_CONFLICT"


def test_the_create_delta_against_the_b132a86_baseline_is_pinned(dec, base):
    a = lambda d, k: {g for g, r in d.items() if r[k] == "CREATE_IDENTITY"}
    now, old = a(dec, "A_outcome"), a(base, "A_outcome")
    assert len(old) == 73 and len(now) == 82 and now - old == ADDED and old - now == {"maxus-mifa-7"}
    assert {r["external_id"] for r in rows(BASE / "create_adjudication.csv")} == old
    for g in ("honda-jazz", "honda-honda-fit"):
        assert dec[g]["A_outcome"] == "IDENTITY_REVIEW" and "STRUCTURAL_CONFLICT" in dec[g]["A_codes"]
    assert dec["honda-honda-stepwagon"]["A_outcome"] == "HOLD" and dec["honda-honda-stepwagon"]["A_primary"] == "NOT_ACTIVATED"
    assert dec["maxus-mifa-7"]["A_outcome"] == "IDENTITY_REVIEW"


def test_structural_conflict_movement_is_consistent_with_the_committed_files(dec, base, summary):
    n = lambda d, k: sum(1 for r in d.values() if "STRUCTURAL_CONFLICT" in r[k].split("|"))
    assert (n(base, "A_codes"), n(dec, "A_codes")) == (9, 17) and (n(base, "B_codes"), n(dec, "B_codes")) == (48, 48)
    s = summary["m5"]["structural"]
    assert (s["A"]["before"], s["A"]["after"], s["B"]["before"], s["B"]["after"]) == (9, 17, 48, 48)
    assert s["A"]["entered"] == ["byd-sealion-5", "byd-sealion-6", "ford-ford-ranger-raptor", "maxus-mifa-7", "maxus-mifa-9", "toyota-hilux-revo", "toyota-hilux-travo", "toyota-land-cruiser-fj"]


def test_no_unsettled_id_is_a_create_and_released_groups_are_not_all_candidates(dec, summary):
    assert all(r["identity_status"] == "settled" for r in dec.values() if r["A_outcome"] == "CREATE_IDENTITY" or r["B_outcome"] == "CREATE_IDENTITY")
    rel = summary["m5"]["parity"] and summary["m5"]["create_sets"]
    assert rel["after"] == 82 and rel["B_creates"] == sorted(g for g, r in dec.items() if r["B_outcome"] == "CREATE_IDENTITY")


def test_registration_units_in_the_report_are_reproducible_from_the_decision_file(dec, summary):
    for mode, key in (("A", "A_outcome"), ("B", "B_outcome")):
        for o in ("CREATE_IDENTITY", "IDENTITY_REVIEW", "HOLD"):
            want = sum(int(r["units_total"]) for r in dec.values() if r[key] == o)
            assert summary["m5"]["units_by_bucket_after"][mode][o]["lifetime_units"] == want, (mode, o)


# ---------------------------------------------------------------------------------------------------------------- the provisional adjudication set
def test_the_adjudication_set_is_exactly_the_committed_mode_a_create_set_with_blank_owner_fields(adj, dec):
    assert {r["external_id"] for r in adj} == {g for g, r in dec.items() if r["A_outcome"] == "CREATE_IDENTITY"} and len(adj) == 82
    assert list(adj[0]) == calibration.COLUMNS
    assert all(r[f] == "" for r in adj for f in calibration.OWNER_FIELDS)
    first = (SHADOW / "review" / "create_adjudication.csv").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# PROVISIONAL") and "not the final truth set" in first
    assert {r["external_id"] for r in adj if r["in_previous_set_b132a86"].startswith("NO")} == ADDED


def test_machine_evidence_is_filled_and_suggestions_are_never_owner_values(adj):
    sugg = [c for c in calibration.COLUMNS if c.endswith("_NON_AUTHORITATIVE")]
    assert sugg and not set(sugg) & set(calibration.OWNER_FIELDS)
    for r in adj:
        assert all(r[c] != "" for c in calibration.COLUMNS if c not in (*calibration.OWNER_FIELDS, "retired_aliases_in_plan", "analyst_note_NON_AUTHORITATIVE", "full_export_relation_changes")), r["external_id"]
        assert r["machine_suggested_discovery_class_NON_AUTHORITATIVE"] in calibration.OWNER_DISCOVERY_CLASSES
        assert r["ir_dry_run_outcome"].startswith("NO_CANDIDATE") and int(r["candidate_pool_size"]) >= 0


def test_unresolved_parity_is_per_subject_and_never_clears_the_other_blockers(adj):
    for r in adj:
        resolved = r["ir_parity_status"] == "IR_PARITY_RESOLVED"
        assert r["current_discovery_activation_authorized"].startswith("NO (projection only")
        assert "OWNER_APPROVAL_PENDING" in r["current_discovery_activation_authorized"] and "GOVERNED_WRITER_NOT_BUILT" in r["current_discovery_activation_authorized"]
        assert ("IR_PARITY_UNRESOLVED" in r["current_discovery_activation_authorized"]) == (not resolved)


# ---------------------------------------------------------------------------------------------------------------- review routing, dispatch and market activity
def test_catalog_alias_and_cross_brand_candidates_are_in_mandatory_owner_review(adj):
    by = {r["external_id"]: r for r in adj}
    owner = {g for g, r in by.items() if r["mandatory_owner_review"] == "YES"}
    assert owner == OWNER_REVIEW
    for g in owner:
        assert by[g]["dispatch_lane"] == "OWNER_REVIEW"
    for g in OWNER_REVIEW - {"maxus-maxus-v80"}:
        assert "POSSIBLE_EXISTING_IDENTITY_CATALOG_ALIAS" in by[g]["review_routing_flags"] and "TDR_CATALOG_ALIAS_EQUALS_PROVIDER_NAME" in by[g]["review_routing_evidence"], g
    assert "POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND" in by["maxus-maxus-v80"]["review_routing_flags"] and "mg.mg_maxus_7" in by["maxus-maxus-v80"]["review_routing_evidence"]
    cb = {r["external_id"] for r in rows(RESULTS / "cross_brand_review.csv")}
    assert {"maxus-maxus-v80", "maxus-mifa-9"} <= cb and OWNER_REVIEW <= cb


def test_the_alias_collisions_are_explained_by_the_ir_evaluator_comparing_name_en_only(export, adj):
    """The nine HOLD->CREATE moves are subjects whose TDR catalog alias equals the provider name; the export (name_en comparison only) says CONTRADICTION. Reported, not patched."""
    for r in adj:
        if "POSSIBLE_EXISTING_IDENTITY_CATALOG_ALIAS" in r["review_routing_flags"]:
            g = r["external_id"]
            assert all(export.ice_tdr[f"{g}|{t}"]["r"] == "CONTRADICTION" for t in export.pool(g)), g
    flagged = [r for r in adj if "POSSIBLE_EXISTING_IDENTITY_CATALOG_ALIAS" in r["review_routing_flags"]]
    assert len(flagged) == 9


def test_dispatch_manifest_never_sends_unknown_or_inactive_to_the_current_lane(adj):
    man = {r["external_id"]: r for r in rows(RESULTS / "dispatch_manifest.csv")}
    assert set(man) == {r["external_id"] for r in adj}
    mk = json.loads((RESULTS / "market_activity.json").read_text(encoding="utf-8"))
    lanes = collections.Counter(r["lane"] for r in man.values())
    assert lanes == {"CURRENT_DISCOVERY": 9, "ACTIVITY_UNCLASSIFIED": 63, "OWNER_REVIEW": 10}
    for g, r in man.items():
        state = mk["per_group"][g]["actual"]
        assert r["activity_state"] == state and r["activation_authorized"] == "NO"
        assert {"OWNER_APPROVAL_PENDING", "GOVERNED_WRITER_NOT_BUILT"} <= set(r["activation_blockers"].split("|"))
        if r["lane"] == "CURRENT_DISCOVERY":
            assert state in ("ACTIVE", "DECLINING", "REACTIVATED") and "POSSIBLE_EXISTING_IDENTITY" not in r["review_flags"]
        assert state != "INACTIVE_INFERRED", "no true zero can exist while Ice absent rows are unconfirmed"
        if state == "UNKNOWN" and r["lane"] != "OWNER_REVIEW":
            assert r["lane"] == "ACTIVITY_UNCLASSIFIED"


def test_market_activity_keeps_absent_rows_unknown_and_states_the_completeness_assumption():
    mk = json.loads((RESULTS / "market_activity.json").read_text(encoding="utf-8"))
    assert mk["explicit_zero_rows_in_package"] == 0 and "INACTIVE_INFERRED" not in mk["actual"]["states"]
    assert mk["actual"]["states"] == {"UNKNOWN": 70, "ACTIVE": 9, "DECLINING": 3}
    assert "NOT AUTHORITATIVE" in mk["what_if_absent_is_zero"]["scenario"] and mk["what_if_absent_is_zero"]["states"].get("INACTIVE_INFERRED") == 25
    assert mk["complete_through"] == "2569-09" and "incomplete month can never supply a true zero" in mk["complete_through_assumption"]


def test_routing_counts_before_and_after_in_the_report(summary):
    rc = summary["m5"]["routing_counts"]
    assert rc["before"] == {"CURRENT_DISCOVERY": 9, "ACTIVITY_UNCLASSIFIED": 62, "OWNER_REVIEW": 2} and rc["after"] == {"CURRENT_DISCOVERY": 9, "ACTIVITY_UNCLASSIFIED": 63, "OWNER_REVIEW": 10}
    assert sum(rc["before"].values()) == 73 and sum(rc["after"].values()) == 82


def test_activity_age_and_volume_columns_do_not_appear_in_any_decision_file(dec):
    assert not [c for c in next(iter(dec.values())) if "lane" in c or "activity" in c]
