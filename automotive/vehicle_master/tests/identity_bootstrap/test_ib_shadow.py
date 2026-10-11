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
from identity_bootstrap.shadow import calibration, ir_rev4, package, post_ir, report, run as shadow_run, stand_in

PKG_PATH = shadow_run.DEFAULT_PACKAGE
needs_package = pytest.mark.skipif(not PKG_PATH.exists(), reason="pinned Ice package not in this checkout")


def toks(*names):
    return [n.split() for n in names]


def test_name_relation_vocabulary():
    rel = stand_in.name_relation
    assert rel(["dmax"], ["dmax"]) == "EQUAL"
    assert rel(["d", "max"], ["d", "max"]) == "EQUAL"
    assert rel(["mg4", "ev"], ["mg4", "electric"]) == "EQUAL_VIA_TOKEN_EQUIV"
    assert rel(["city", "hatchback"], ["city"]) == "SUBJECT_FINER"
    assert rel(["hilux", "travo"], ["hilux", "travo", "cab"]) == "SUBJECT_COARSER"
    assert rel(["hilux", "revo"], ["hilux", "travo"]) == "SIBLING"
    assert rel(["d", "max"], ["mu", "x"]) == "CONTRADICTION"
    assert rel([], ["x"]) == "UNAVAILABLE"
    assert rel(["fortunar"], ["fortuner"]) == "FUZZY"


def test_the_stand_in_contains_no_lexical_correction_of_its_own():
    """PR #200 owns the corrected relation rules; the stand-in must not carry a second implementation of them."""
    import inspect
    src = inspect.getsource(stand_in) + inspect.getsource(ir_rev4)
    assert "refined" not in src and "non_distinctive" not in src and "allow_tokens_with_digits" not in src
    assert "refined" not in inspect.signature(stand_in.name_relation).parameters
    # the draft semantics are still what the population is built from: a one-digit difference IS a typo there, and only IR's export can say otherwise
    assert stand_in.name_relation(["xc60"], ["xc90"]) == "FUZZY"
    assert ir_rev4.adjudicate("FUZZY", None) == "CONTRADICTION" and ir_rev4.adjudicate("SIBLING", None) == "CONTRADICTION"
    assert ir_rev4.adjudicate("CONTRADICTION", "EQUAL_VIA_MODEL_ALIAS") == "EQUAL_VIA_MODEL_ALIAS"
    assert ir_rev4.adjudicate("SUBJECT_FINER", None) == "SUBJECT_FINER" and ir_rev4.adjudicate("EQUAL", None) == "EQUAL"


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
    ir = ir_rev4.load()
    a = shadow_run.run("A", ir=ir)
    b = shadow_run.run("B", pkg=a["package"], ir=ir)
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
    assert count(a) == {"CREATE_IDENTITY": 73, "IDENTITY_REVIEW": 89, "HOLD": 1038}
    assert count(b) == {"CREATE_IDENTITY": 72, "IDENTITY_REVIEW": 375, "HOLD": 753}


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
def test_mode_b_stress_scenario_created_a_subset_of_mode_a_on_this_snapshot(runs):
    """OBSERVATION, not a law. Mode B force-activates every subject (a stress scenario, not an upper bound on CREATE): the extra activated subjects can form batch conflicts
    (which is why B has one fewer CREATE here) and could in principle also remove a conflict. This test only pins what this pinned package shows."""
    a, b = runs
    ids = lambda r: {d["subject"]["entity_id"] for d in r["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    assert ids(b) <= ids(a)
    assert ids(a) - ids(b) == {"maxus-mifa-7"}


@needs_package
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
    ir = ir_rev4.load()
    again = report.analyse(shadow_run.run("A", pkg=a["package"], ir=ir), shadow_run.run("B", pkg=a["package"], ir=ir))
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
    assert "POSSIBLE_MODEL_CODE" in e300 and "DUPLICATE_CANONICAL_SUSPECTED" in e300
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
    report.write_transitions(summary["m4"]["transitions"], tmp_path / "transitions_vs_m3.csv")
    report.write_market(a, summary, tmp_path)
    report.write_routing(summary, tmp_path)
    for name in ("decisions.csv", "REPORT.md", "transitions_vs_m3.csv", "market_activity.json", "market_activity.md", "dispatch_manifest.csv", "cross_brand_review.csv", "ir_parity_unresolved.csv"):
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
    assert {r["external_id"] for r in got} == creates and len(got) == len(creates) == 73
    assert set(got[0]) == set(calibration.COLUMNS)
    for col in ("provider", "external_id", "provider_model_name", "provider_brand", "proposed_canonical_name", "proposed_canonical_id", "first_seen", "last_seen", "lifetime_units", "last12_units",
                "identity_status", "lineage_state", "nearest_existing_canonical_identities", "relation_evidence", "brand_relation", "shape_flags", "lexical_flags", "evidence_tier",
                "bootstrap_reason_codes", "legacy_r6_candidate_status", "changed_by_pr200_rev4_relations", "owner_verdict", "owner_canonical_model_id", "owner_discovery_class", "owner_notes"):
        assert col in got[0], col
    assert all(r[f] == "" for r in got for f in calibration.OWNER_FIELDS), "the owner fills the owner fields; the shadow run must never pre-fill them"
    machine = [c for c in calibration.COLUMNS if c not in calibration.OWNER_FIELDS]
    assert all(r[c] != "" for r in got for c in machine if c not in ("retired_aliases_in_plan", "analyst_note_NON_AUTHORITATIVE", "pr200_relation_changes")), "machine evidence must be filled for every row"
    assert all(c.endswith("_NON_AUTHORITATIVE") for c in machine if "suggested" in c or "analyst" in c or "what_if" in c)
    added = {r["external_id"] for r in got if r["in_previous_set_milestone3"].startswith("NO")}
    assert added == {"maxus-maxus-v80", "maxus-mifa-7", "mazda-mazda-mx-30", "mazda-mazda6e", "nissan-nissan-be-1", "peugeot-peugeot-5008", "volkswagen-volkswagen-t-roc", "volkswagen-vw-t-cross", "volvo-volvo-es90"}


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
def test_cross_pr_relation_parity_with_the_pinned_pr200_rev4_export(built):
    a, _, summary, _ = built
    par = summary["m4"]["parity"]
    assert par["pr200_commit"] == "1f73aee1834697cbd439291d0074293c30446e5b" == ir_rev4.PR200_COMMIT
    for pop in ("ice_ice", "ice_tdr"):
        assert par[pop]["exported_pairs_missing_or_relabelled"] == [], pop
        assert par[pop]["fuzzy_or_sibling_not_in_export"] == [], pop
        assert all(x == y for x, y in par[pop]["corrected_kinds_equal"].values()), pop
    ir = ir_rev4.load()
    assert ir["relation_counts"]["ice_ice"]["FUZZY"] == 7 and ir["relation_counts"]["ice_ice"]["SIBLING"] == 307 and ir["relation_counts"]["ice_tdr"]["SIBLING"] == 55
    assert ir["relation_counts"]["before_ice_ice"]["FUZZY"] == 54 and ir["relation_counts"]["before_ice_ice"]["SIBLING"] == 1152
    rel = {(s["entity_id"], r["peer_id"]): r["name_relation"] for s in a["snapshot"]["subjects"] for r in s["relations"]}
    assert rel[("honda-honda-stepwagon", "honda.step_wgn")] == "EQUAL_VIA_MODEL_ALIAS"
    assert rel[("honda-honda-fit", "honda-jazz")] == "EQUAL_VIA_MODEL_ALIAS"
    assert not any(rel.get(k) in ("FUZZY", "SIBLING") for k in (("volvo-volvo-xc60", "volvo-volvo-xc90"), ("mazda-mazda6e", "mazda.mazda6")))


def test_the_vendored_export_is_exactly_the_pinned_commit():
    """If the pinned commit is in this clone, re-read its blobs and check the recorded sha256 and the vendored pairs."""
    import subprocess
    repo = Path(shadow_run.__file__).resolve().parents[4]
    ok = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", ir_rev4.PR200_COMMIT], capture_output=True).returncode == 0
    if not ok:
        pytest.skip("PR #200 commit not present in this clone")
    ir = ir_rev4.load()
    for name, digest in ir["provenance"]["sources_sha256"].items():
        blob = ir_rev4._git_show(repo, ir_rev4.PR200_COMMIT, f"{ir_rev4.SOURCE_DIR}/{name}")
        assert hashlib.sha256(blob).hexdigest() == digest, name
    after = json.loads(ir_rev4._git_show(repo, ir_rev4.PR200_COMMIT, f"{ir_rev4.SOURCE_DIR}/after_rev4.json"))
    assert after["ice_ice_relation_pairs"] == ir["ice_ice_relation_pairs"] and after["ice_tdr_relation_pairs"] == ir["ice_tdr_relation_pairs"]


@needs_package
def test_decision_transitions_against_milestone_3_are_pinned(built):
    """Any change to these is a reviewed change: the nine new CREATEs, the three that left, and the structural-conflict movement."""
    _, _, summary, _ = built
    m4 = summary["m4"]
    A, B = m4["diff"]["A"], m4["diff"]["B"]
    assert A["transition_matrix"] == {"CREATE_IDENTITY -> CREATE_IDENTITY": 64, "CREATE_IDENTITY -> HOLD": 1, "CREATE_IDENTITY -> IDENTITY_REVIEW": 2, "HOLD -> CREATE_IDENTITY": 3,
                                      "HOLD -> HOLD": 1037, "HOLD -> IDENTITY_REVIEW": 4, "IDENTITY_REVIEW -> CREATE_IDENTITY": 6, "IDENTITY_REVIEW -> IDENTITY_REVIEW": 83}
    assert A["create_removed"] == ["honda-honda-fit", "honda-honda-stepwagon", "honda-jazz"] == B["create_removed"]
    assert A["create_added"] == m4["create_sets"]["added_vs_m3"] and len(A["create_added"]) == 9
    assert set(B["create_added"]) == set(A["create_added"]) - {"maxus-mifa-7"}
    assert (m4["structural"]["A"]["before"], m4["structural"]["A"]["after"]) == (24, 9) and (m4["structural"]["B"]["before"], m4["structural"]["B"]["after"]) == (105, 48)
    assert m4["structural"]["A"]["entered"] == ["honda-honda-fit", "honda-jazz"]
    assert len(m4["transitions"]) == 74


@needs_package
def test_the_honda_synonym_outcomes(runs):
    a, b = runs
    by = {m: {d["subject"]["entity_id"]: d for d in r["decisions"]} for m, r in (("A", a), ("B", b))}
    for gid in ("honda-jazz", "honda-honda-fit"):
        assert by["A"][gid]["outcome"] == "IDENTITY_REVIEW" and "STRUCTURAL_CONFLICT" in by["A"][gid]["reason_codes"], "one vehicle in two Ice groups: reviewed together, never created twice"
    assert by["A"]["honda-honda-stepwagon"]["outcome"] == "HOLD" and by["A"]["honda-honda-stepwagon"]["primary_reason"] == "NOT_ACTIVATED"
    assert by["B"]["honda-honda-stepwagon"]["outcome"] != "CREATE_IDENTITY"


@needs_package
def test_create_safety_of_the_released_no_candidate_groups(built):
    """The 177 NO_CANDIDATE groups of PR #200 are not all Bootstrap candidates: only settled ids can be created, and only seven are."""
    _, _, summary, _ = built
    rel = summary["m4"]["released_no_candidate"]
    assert rel["pr200_count"] == rel["present_in_bootstrap_run"] == 177
    assert rel["identity_status"] == {"unmapped_name": 115, "provisional": 30, "settled": 32}
    for mode in ("A", "B"):
        assert set(rel[mode]["create"]) <= set(rel["settled_among_released"])
        assert len(rel[mode]["create"]) == 7
    assert "mazda-mazda6e" in rel["A"]["create"] and "volkswagen-vw-t-cross" in rel["A"]["create"]


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
    creates = {d["subject"]["entity_id"] for d in a["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    assert creates <= set(r6)
    assert all(row[1] == "PROPOSED" for rows in r6.values() for row in rows), "no remaining CREATE group has an approved/matched legacy R6 row"
