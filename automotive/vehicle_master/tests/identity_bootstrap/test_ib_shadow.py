"""The shadow run: stand-in unit tests, and invariants of the real run on the pinned M7.0 package (skipped if the package file is absent)."""
from __future__ import annotations

import collections
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

import ib_support as S
from identity_bootstrap import shadow
from identity_bootstrap.shadow import calibration, ir_export, package, post_ir, report, run as shadow_run, stand_in

PKG_PATH = shadow_run.DEFAULT_PACKAGE
needs_package = pytest.mark.skipif(not PKG_PATH.exists(), reason="pinned Ice package not in this checkout")


def toks(*names):
    return [n.split() for n in names]


def test_the_stand_in_contains_no_matcher_and_no_default_for_a_missing_pair():
    """PR #200 owns every lexical relation; the stand-in only looks relations up in the verified export."""
    import inspect
    src = inspect.getsource(stand_in)
    for gone in ("def name_relation", "_edit1", "TOKEN_EQUIVALENCE", "FUZZY_MIN_TOKEN", "STRENGTH", "adjudicate", "refined", "CONTRADICTION\"\n    return"):
        assert gone not in src, gone
    assert not hasattr(stand_in, "name_relation")
    with pytest.raises(ImportError):
        from identity_bootstrap.shadow import ir_rev4  # noqa: F401  (the partial-export bridge was removed once full parity existed)


def test_the_stand_in_is_labelled_as_a_stand_in():
    assert "STAND-IN" in stand_in.__doc__ and "STAND-IN" in shadow.__doc__


@needs_package
def test_a_package_that_is_not_the_pinned_one_is_refused(tmp_path):
    other = tmp_path / "TDR_FULL_other.zip"
    other.write_bytes(PKG_PATH.read_bytes() + b"x")
    with pytest.raises(package.PackageError):
        package.load(other)


@pytest.fixture(scope="module")
def runs():
    if not PKG_PATH.exists():
        pytest.skip("pinned Ice package not in this checkout")
    export = ir_export.load()
    a = shadow_run.run("A", export=export)
    b = shadow_run.run("B", pkg=a["package"], export=export)
    return a, b


@needs_package
def test_the_run_covers_all_1200_groups_and_is_the_pinned_package(runs):
    a, b = runs
    assert a["package"]["sha256"] == package.PINNED["sha256"]
    assert len(a["decisions"]) == len(b["decisions"]) == 1200
    assert collections.Counter(s["identity_status"] for s in a["snapshot"]["subjects"]) == {"settled": 495, "unmapped_name": 591, "provisional": 114}
    assert {d["outcome"] for d in a["decisions"]} <= set(S.OUTCOMES)
    assert S.validate_input(a["snapshot"]) == []


@needs_package
def test_golden_shadow_numbers(runs):
    """Pinned so that any change to a word list, a pattern, the stand-in or the engine is a visible, reviewed change to these numbers."""
    a, b = runs
    count = lambda r: dict(collections.Counter(d["outcome"] for d in r["decisions"]))
    assert count(a) == {"CREATE_IDENTITY": 82, "IDENTITY_REVIEW": 127, "HOLD": 991}
    assert count(b) == {"CREATE_IDENTITY": 82, "IDENTITY_REVIEW": 365, "HOLD": 753}


@needs_package
def test_only_plans_never_writes(runs):
    for r in runs:
        creates = [d for d in r["decisions"] if d["outcome"] == "CREATE_IDENTITY"]
        assert all(d["write_plan"] and d["identity"] for d in creates)
        assert all(d["write_plan"] is None and d["identity"] is None for d in r["decisions"] if d["outcome"] != "CREATE_IDENTITY")
        assert all(S.validate_decision(d) == [] for d in r["decisions"])
        for d in creates:
            shell = next(o for o in d["write_plan"]["operations"] if o["op"] == "INSERT_IDENTITY_SHELL")["values"]
            assert set(shell) == set(S.policy()["writes"]["shell_columns"])
            assert shell["identity_state"] == "DISCOVERED" and shell["enrichment_state"] == "PENDING"
            assert d["write_plan"]["apply_mode"] == "PROPOSE"


@needs_package
def test_mode_b_stress_scenario_created_the_same_set_as_mode_a_on_this_snapshot(runs):
    """OBSERVATION, not a law. Mode B force-activates every subject (a stress scenario, not an upper bound on CREATE): extra activated subjects can form batch conflicts
    (the previous export-partial run had one fewer CREATE in B). With the full export the sets coincide on this pinned package; this test pins only that observation."""
    a, b = runs
    ids = lambda r: {d["subject"]["entity_id"] for d in r["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    assert ids(a) == ids(b) and len(ids(a)) == 82


@needs_package
def test_no_unsettled_identity_is_ever_created(runs):
    for r in runs:
        status = {s["entity_id"]: s["identity_status"] for s in r["snapshot"]["subjects"]}
        for d in r["decisions"]:
            if d["outcome"] == "CREATE_IDENTITY":
                assert status[d["subject"]["entity_id"]] == "settled"
            if status[d["subject"]["entity_id"]] != "settled":
                assert d["outcome"] == "HOLD"


@needs_package
def test_volume_never_decides_on_the_real_data(runs):
    a, _ = runs
    base = [(d["subject"]["entity_id"], d["outcome"], d["reason_codes"], d["identity"]) for d in a["decisions"]]
    for fill in (0, 3, 10_000_000):
        snap = copy.deepcopy(a["snapshot"])
        for s in snap["subjects"]:
            s["units"] = fill
        out = S.run_decide(snap, impl="engine")
        assert [(d["subject"]["entity_id"], d["outcome"], d["reason_codes"], d["identity"]) for d in out] == base


@needs_package
def test_activity_age_and_volume_fields_cannot_change_any_decision_on_the_real_data(runs):
    """Routing context only: set units, first_seen to extremes (very old / brand new / absent) on every real subject and the decisions must be identical."""
    a, _ = runs
    key = lambda out: [(d["subject"]["entity_id"], d["outcome"], d["reason_codes"], d["identity"]) for d in out]
    base = key(a["decisions"])
    for units, seen in ((0, "2500-01"), (10_000_000, "2599-12"), (1, "2564-01"), (7, "2569-09")):
        snap = copy.deepcopy(a["snapshot"])
        for s in snap["subjects"]:
            s["units"] = units
            if "first_seen" in s:
                s["first_seen"] = seen
        assert key(S.run_decide(snap, impl="engine")) == base, (units, seen)
    assert all("monthly" not in s and "last12" not in s for s in a["snapshot"]["subjects"]), "monthly series must never reach Bootstrap's input"


@needs_package
def test_engine_and_oracle_agree_on_all_1200_real_subjects(runs):
    for r in runs:
        assert S.run_decide(copy.deepcopy(r["snapshot"]), impl="oracle") == r["decisions"]


@needs_package
def test_the_real_run_is_deterministic_and_the_report_is_byte_stable(runs, tmp_path):
    a, b = runs
    first = report.analyse(a, b)
    export = ir_export.load()
    again = report.analyse(shadow_run.run("A", pkg=a["package"], export=export), shadow_run.run("B", pkg=a["package"], export=export))
    for s in (first, again):
        s.pop("inputs")["engine_seconds"]
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)


@needs_package
def test_the_known_mutual_split_is_held_not_guessed(runs):
    a, _ = runs
    by = {d["subject"]["entity_id"]: d for d in a["decisions"]}
    for gid in ("mini-mini-cooper-ev", "mini-mini-jcw-convertible"):
        assert by[gid]["outcome"] == "HOLD" and "LINEAGE_UNRESOLVED" in by[gid]["reason_codes"]


@needs_package
def test_the_brief_examples_on_real_names(runs):
    a, b = runs
    by = {m: {d["subject"]["entity_id"]: d for d in r["decisions"]} for m, r in (("A", a), ("B", b))}
    for mode in "AB":
        for gid in ("mercedes-benz-mercedes-benz-e300", "NISSAN|BVL2RTYD23FHP A", "honda-city-hatchback", "toyota-hilux-revo"):
            assert by[mode][gid]["outcome"] != "CREATE_IDENTITY" and by[mode][gid]["write_plan"] is None, (mode, gid)
        assert by[mode]["ISUZU|ไม่ระบุ"]["outcome"] == "HOLD" and "NAME_UNSPECIFIED" in by[mode]["ISUZU|ไม่ระบุ"]["reason_codes"]
        assert by[mode]["NISSAN|BVL2RTYD23FHP A"]["primary_reason"] == "PROVIDER_RAW_NAME"
    e300 = by["B"]["mercedes-benz-mercedes-benz-e300"]["reason_codes"]
    assert "POSSIBLE_MODEL_CODE" in e300, "still reviewed (model code + lineage); the old duplicate suspicion came from the stand-in's catalog-alias match, which the IR export does not carry"
    assert {"PROVIDER_FINER_THAN_TDR", "POSSIBLE_BODY_VARIANT"} <= set(by["B"]["honda-city-hatchback"]["reason_codes"])


@needs_package
def test_the_shadow_run_is_read_only(runs, tmp_path):
    watched = [PKG_PATH, *sorted(shadow_run.DEFAULT_MODELS.glob("*.json")), shadow_run.DEFAULT_LEGACY]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    a, b = runs
    summary = report.analyse(a, b)
    paths = report.write_files(summary, a, b, tmp_path)
    assert {p.name for p in paths} == {"decisions.csv", "summary.json", "REPORT.md", "plans_sample.json"} and all(tmp_path in p.parents for p in paths)
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched} == before


@pytest.fixture(scope="module")
def built():
    if not PKG_PATH.exists():
        pytest.skip("pinned Ice package not in this checkout")
    return report.build_all()


@needs_package
def test_the_committed_results_match_the_run(built, tmp_path):
    """The reviewed REPORT.md / decisions.csv / adjudication CSV in the repo are exactly what the current code produces."""
    committed = Path(shadow_run.__file__).parent / "results" / "2569-09_v3_M7.0"
    if not committed.exists():
        pytest.skip("results not committed yet")
    a, b, summary, rows = built
    report.write_files(summary, a, b, tmp_path)
    report.write_transitions(summary["m5"]["transitions"], tmp_path / "transitions_vs_b132a86.csv")
    report.write_market(a, summary, tmp_path)
    report.write_routing(summary, tmp_path)
    for name in ("decisions.csv", "REPORT.md", "transitions_vs_b132a86.csv", "market_activity.json", "market_activity.md", "dispatch_manifest.csv", "cross_brand_review.csv", "parity_unresolved.csv", "dry_run_vs_bootstrap.csv", "collision_analysis.json"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (committed / name).read_text(encoding="utf-8"), f"{name} is stale: re-run python -m identity_bootstrap.shadow --out {committed}"
    review = Path(shadow_run.__file__).parent / "review" / "create_adjudication.csv"
    calibration.write_adjudication(rows, tmp_path / "create_adjudication.csv")
    assert (tmp_path / "create_adjudication.csv").read_text(encoding="utf-8") == review.read_text(encoding="utf-8"), "create_adjudication.csv is stale"


@needs_package
def test_the_provisional_adjudication_set_covers_every_create_and_leaves_every_owner_field_blank(built):
    a, _, _, rows = built
    creates = {d["subject"]["entity_id"] for d in a["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    path = Path(shadow_run.__file__).parent / "review" / "create_adjudication.csv"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# PROVISIONAL candidate set") and "VALID_MISSING_CANONICAL | EXISTING_IDENTITY | VARIANT_TRIM_CODE | AMBIGUOUS" in text.splitlines()[0]
    assert "RECENT_NEW_MODEL | ACTIVE_CATALOG_GAP | HISTORICAL_BACKFILL" in text.splitlines()[0]
    got = list(csv.DictReader(text.splitlines()[1:]))
    assert {r["external_id"] for r in got} == creates and len(got) == len(creates) == 82
    assert set(got[0]) == set(calibration.COLUMNS)
    for col in ("provider", "external_id", "provider_model_name", "provider_brand", "proposed_canonical_name", "proposed_canonical_id", "first_seen", "last_seen", "lifetime_units", "last12_units",
                "identity_status", "lineage_state", "nearest_existing_canonical_identities", "relation_evidence", "brand_relation", "shape_flags", "lexical_flags", "evidence_tier",
                "bootstrap_reason_codes", "legacy_r6_candidate_status", "changed_by_full_export_relations", "ir_parity_status", "ir_parity_reasons", "candidate_pool_size", "ir_dry_run_outcome", "owner_verdict", "owner_canonical_model_id", "owner_discovery_class", "owner_notes"):
        assert col in got[0], col
    assert all(r[f] == "" for r in got for f in calibration.OWNER_FIELDS), "the owner fills the owner fields; the shadow run must never pre-fill them"
    machine = [c for c in calibration.COLUMNS if c not in calibration.OWNER_FIELDS]
    assert all(r[c] != "" for r in got for c in machine if c not in ("retired_aliases_in_plan", "analyst_note_NON_AUTHORITATIVE", "full_export_relation_changes")), "machine evidence must be filled for every row"
    assert all(c.endswith("_NON_AUTHORITATIVE") for c in machine if "suggested" in c or "analyst" in c or "what_if" in c)
    added = {r["external_id"] for r in got if r["in_previous_set_b132a86"].startswith("NO")}
    assert added == {"audi-audi-a8l", "audi-audi-s3", "bmw-x2", "byd-e6", "isuzu-isuzu-cab4", "jaecoo-jaecoo-j5", "jaecoo-jaecoo-j7", "volkswagen-volkswagen-multivan", "volkswagen-vw-idbuzz", "wuling-binguo"}


def test_machine_suggestions_cannot_act_as_owner_truth():
    """No code path reads or copies the non-authoritative columns; only the CSV writer defines the owner fields."""
    root = Path(shadow_run.__file__).parent.parent
    for f in root.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        if f.name == "calibration.py":
            continue
        for needle in ("owner_verdict", "owner_discovery_class", "owner_canonical_model_id", "_NON_AUTHORITATIVE", "SUGGESTED_DISCOVERY"):
            assert needle not in text, f"{f.relative_to(root)} mentions {needle}"
    src = (root / "shadow" / "calibration.py").read_text(encoding="utf-8")
    assert 'f: "" for f in OWNER_FIELDS' in src, "owner fields are written blank, never from a suggestion"
    # the suggestion vocabulary is a strict subset of the owner's, but is a different column and is never assigned to an owner column
    assert set(calibration.SUGGESTED_DISCOVERY.values()) <= set(calibration.OWNER_DISCOVERY_CLASSES)
    assert not any("owner" in c and "NON_AUTHORITATIVE" in c for c in calibration.COLUMNS)


@needs_package
def test_full_parity_with_the_pinned_pr200_export_on_the_real_run(built):
    """Every relation Bootstrap saw is the export's; the whole evaluated population was read; the shadow's candidates are exactly the export pools."""
    a, _, summary, _ = built
    par = summary["m5"]["parity"]
    assert summary["m5"]["pr200"]["commit"] == "eed76aa6ad6380afea60d604e5e7eac87abedb06" == ir_export.PIN["producer_commit"]
    lx = par["lexical_relations"]
    assert lx["snapshot_relations_wrong"] == []
    for pop, n in (("ice_ice", 26505), ("ice_tdr", 12412)):
        assert lx[pop]["evaluated_pairs"] == lx[pop]["pairs_read_by_the_shadow"] == n and lx[pop]["all_pairs_read"] is True
        assert lx[pop]["snapshot_relations_not_in_export_or_relabelled"] == [] and lx[pop]["export_relations_not_passed_on"] == []
        assert lx[pop]["counts_equal_manifest_for_all_nine_kinds"] is True
    pp = par["candidate_pools"]
    assert pp["shadow_candidates_outside_pool"] == [] and pp["pool_members_not_read"] == [] and pp["subjects_with_empty_pool"] == 226
    export = a["export"]
    rel = {(s["entity_id"], r["peer_id"]): r["name_relation"] for s in a["snapshot"]["subjects"] for r in s["relations"]}
    assert rel[("honda-honda-stepwagon", "honda.step_wgn")] == "EQUAL_VIA_MODEL_ALIAS" and rel[("honda-honda-fit", "honda-jazz")] == "EQUAL_VIA_MODEL_ALIAS"
    assert ("volvo-volvo-xc60", "volvo-volvo-xc90") not in rel and ("mazda-mazda6e", "mazda.mazda6") not in rel
    assert export.consulted_ice_tdr == set(export.ice_tdr) and export.consulted_ice_ice == set(export.ice_ice)


@needs_package
def test_subject_level_parity_status_clears_only_what_meets_every_requirement(built):
    _, _, summary, _ = built
    sub = summary["m5"]["parity"]["subjects"]
    assert sub["resolved"] == 1192 and sub["unresolved"] == 8
    assert set(sub["unresolved_ids_and_reasons"]) == {"JETOUR|ไม่ระบุ", "MERCEDES AMG|SL 43", "MERCEDES AMG|SL 55 4MATIC", "MERCEDESBENZ MAYBACH|S680 4 M", "RANGE ROVER|AUTOBIOGRAPHY P400E LWB",
                                                    "RANGE ROVER|EVOQUE 2 2 SD4 DYNAMIC", "RANGE ROVER|EVOQUE 2 2L SD4", "maxus-maxus-epc1a"}
    assert all(r and all(x.startswith("BRAND_RESOLUTION_VS_POOL") for x in r) for r in sub["unresolved_ids_and_reasons"].values())
    for g, v in summary["m5"]["ir_parity_status"].items():
        assert v["status"] == ("IR_PARITY_UNRESOLVED" if v["reasons"] else "IR_PARITY_RESOLVED")


@needs_package
def test_decision_transitions_against_the_b132a86_baseline_are_pinned(built):
    """Let the verified relations decide: nothing is held at the old 73."""
    _, _, summary, _ = built
    m5 = summary["m5"]
    assert m5["counts"]["before"]["A"] == {"CREATE_IDENTITY": 73, "IDENTITY_REVIEW": 89, "HOLD": 1038} and m5["counts"]["after"]["A"] == {"CREATE_IDENTITY": 82, "IDENTITY_REVIEW": 127, "HOLD": 991}
    assert m5["counts"]["before"]["B"] == {"CREATE_IDENTITY": 72, "IDENTITY_REVIEW": 375, "HOLD": 753} and m5["counts"]["after"]["B"] == {"CREATE_IDENTITY": 82, "IDENTITY_REVIEW": 365, "HOLD": 753}
    cs = m5["create_sets"]
    assert cs["removed"] == ["maxus-mifa-7"] and len(cs["added"]) == 10 and cs["unchanged"] == 72 and cs["in_A_not_B"] == [] and cs["in_B_not_A"] == []
    assert m5["review_hold_moves"]["A"] == {"CREATE_IDENTITY -> IDENTITY_REVIEW": 1, "HOLD -> CREATE_IDENTITY": 9, "HOLD -> IDENTITY_REVIEW": 38, "IDENTITY_REVIEW -> CREATE_IDENTITY": 1}
    assert (m5["structural"]["A"]["before"], m5["structural"]["A"]["after"]) == (9, 17) and (m5["structural"]["B"]["before"], m5["structural"]["B"]["after"]) == (48, 48)
    assert len(m5["transitions"]) == 77
    for t in m5["transitions"]:
        assert t["relation_changes"] and t["A_codes_after"] is not None
    # the nine HOLD -> CREATE moves are subjects whose old EQUAL came from the TDR catalog's own aliases, which the IR export does not compare
    assert {g for g in cs["added"] if m5["added_detail"][g]["A_before"].startswith("HOLD")} == {"audi-audi-a8l", "audi-audi-s3", "byd-e6", "isuzu-isuzu-cab4", "jaecoo-jaecoo-j5", "jaecoo-jaecoo-j7", "volkswagen-volkswagen-multivan", "volkswagen-vw-idbuzz", "wuling-binguo"}


@needs_package
def test_the_honda_synonym_and_maxus_outcomes(runs):
    a, b = runs
    by = {m: {d["subject"]["entity_id"]: d for d in r["decisions"]} for m, r in (("A", a), ("B", b))}
    for gid in ("honda-jazz", "honda-honda-fit"):
        assert by["A"][gid]["outcome"] == "IDENTITY_REVIEW" and "STRUCTURAL_CONFLICT" in by["A"][gid]["reason_codes"]
    assert by["A"]["honda-honda-stepwagon"]["outcome"] == "HOLD" and by["A"]["honda-honda-stepwagon"]["primary_reason"] == "NOT_ACTIVATED"
    assert by["A"]["maxus-mifa-7"]["outcome"] == "IDENTITY_REVIEW" and "STRUCTURAL_CONFLICT" in by["A"]["maxus-mifa-7"]["reason_codes"]
    assert by["A"]["maxus-maxus-v80"]["outcome"] == "CREATE_IDENTITY"      # still a CREATE projection; routed to mandatory owner review, never to the current lane


@needs_package
def test_catalog_alias_collisions_are_owner_review_not_current_discovery(built):
    _, _, summary, rows = built
    rev = summary["m5"]["routing"]["reviews"]
    owner = {g for g, r in rev.items() if r["mandatory_owner_review"]}
    assert owner == {"audi-audi-a8l", "audi-audi-s3", "byd-e6", "isuzu-isuzu-cab4", "jaecoo-jaecoo-j5", "jaecoo-jaecoo-j7", "maxus-maxus-v80", "volkswagen-volkswagen-multivan", "volkswagen-vw-idbuzz", "wuling-binguo"}
    lanes = {r["external_id"]: r["lane"] for r in summary["m5"]["routing"]["dispatch"] if r["bootstrap_outcome"] == "CREATE_IDENTITY"}
    assert all(lanes[g] == "OWNER_REVIEW" for g in owner)
    assert summary["m5"]["routing_counts"]["after"] == {"ACTIVITY_UNCLASSIFIED": 63, "CURRENT_DISCOVERY": 9, "OWNER_REVIEW": 10}


@needs_package
def test_create_safety_of_the_released_no_candidate_groups_and_empty_pools(built):
    _, _, summary, _ = built
    m5 = summary["m5"]
    dec = {d["subject"]["entity_id"]: d for d in built[0]["decisions"]}
    # an empty pool is never an authorization: every empty-pool subject is either not a CREATE or a CREATE that still carries every blocker
    for r in m5["routing"]["dispatch"]:
        assert r["activation_authorized"] is False and "OWNER_APPROVAL_PENDING" in r["activation_blockers"] and "GOVERNED_WRITER_NOT_BUILT" in r["activation_blockers"]
    assert all(dec[g]["outcome"] != "CREATE_IDENTITY" for g in ("JETOUR|ไม่ระบุ", "MERCEDES AMG|SL 43"))


@needs_package
def test_the_adapter_never_offers_a_sub_brand_as_a_parent_brand_spelling(runs):
    a, _ = runs
    policy = S.policy()
    forbidden = {"gwm": {"haval", "ora", "tank", "wey"}, "chery": {"omoda", "jetour"}}
    for s in a["snapshot"]["subjects"]:
        bid = s["brand"].get("brand_id")
        if bid in forbidden:
            assert not ({x.lower() for x in s["brand"]["spellings"]} & forbidden[bid]), (s["entity_id"], bid)
    assert policy["brand"]["sub_brands"]["gwm"] and policy["brand"]["family"]["duplicate_relations"] == ["ALIAS_RELABEL"]


@needs_package
def test_related_marques_are_passed_as_family_not_as_spellings(runs):
    a, _ = runs
    changan = [s for s in a["snapshot"]["subjects"] if s["brand"].get("brand_id") == "changan"]
    assert changan and all("deepal" not in {x.lower() for x in s["brand"]["spellings"]} for s in changan)
    assert all(s["brand"]["family"] == [{"brand_id": "deepal", "relation": "ALIAS_RELABEL", "spellings": ["Deepal"]}] for s in changan)


@needs_package
def test_the_live_universe_record_is_read_only_evidence_and_consistent(runs):
    rec = json.loads((Path(shadow_run.__file__).parent / "universe" / "vehicle_master_live_2026-10-11.json").read_text(encoding="utf-8"))
    a, _ = runs
    assert a["catalog"]["verification"]["comparison_with_file_snapshot"]["model_ids_equal"] is True
    assert len(a["catalog"]["identities"]) == 323 and rec
    r6 = json.loads((Path(shadow_run.__file__).parent / "universe" / "r6_crosswalk_for_create_candidates.json").read_text(encoding="utf-8"))["rows"]
    assert len(r6) == 489 and sum(len(v) for v in r6.values()) == 490, "the legacy R6 rows come from the PR #200 pinned input, not from Production"
    creates = {d["subject"]["entity_id"] for d in a["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    assert {g for g in creates if any(row[1] == "AUTO" for row in r6.get(g, []))} == {"audi-audi-a8l", "wuling-binguo"}, "the legacy matcher itself linked these two CREATE candidates (AUTO); both are mandatory owner review"
    assert collections.Counter(row[1] for rows in r6.values() for row in rows) == {"PROPOSED": 408, "AUTO": 82}
