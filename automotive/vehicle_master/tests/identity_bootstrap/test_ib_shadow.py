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
from identity_bootstrap.shadow import calibration, package, report, run as shadow_run, stand_in

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


def test_refined_relations_do_not_call_a_version_a_typo():
    assert stand_in.name_relation(["xc60"], ["xc90"], refined=False) == "FUZZY", "the IR draft's rule calls a one-digit difference a typo"
    assert stand_in.name_relation(["xc60"], ["xc90"], refined=True) == "CONTRADICTION"
    assert stand_in.name_relation(["db11"], ["db12"], refined=True) == "CONTRADICTION"
    assert stand_in.name_relation(["gr", "yaris"], ["gr", "corolla"], refined=True, non_distinctive=frozenset({"gr"})) == "CONTRADICTION"
    assert stand_in.name_relation(["hilux", "revo"], ["hilux", "travo"], refined=True) == "SIBLING"


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
    a = shadow_run.run("A")
    b = shadow_run.run("B", pkg=a["package"])
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
    assert count(a) == {"CREATE_IDENTITY": 67, "IDENTITY_REVIEW": 89, "HOLD": 1044}
    assert count(b) == {"CREATE_IDENTITY": 67, "IDENTITY_REVIEW": 380, "HOLD": 753}


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
def test_creates_are_the_same_whether_or_not_the_resolver_stand_in_filters_first(runs):
    a, b = runs
    ids = lambda r: {d["subject"]["entity_id"] for d in r["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    assert ids(a) == ids(b), "Bootstrap's own duplicate defences must catch what the resolver would have mapped"


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
def test_engine_and_oracle_agree_on_all_1200_real_subjects(runs):
    for r in runs:
        assert S.run_decide(copy.deepcopy(r["snapshot"]), impl="oracle") == r["decisions"]


@needs_package
def test_the_real_run_is_deterministic_and_the_report_is_byte_stable(runs, tmp_path):
    a, b = runs
    first = report.analyse(a, b)
    again = report.analyse(shadow_run.run("A", pkg=a["package"]), shadow_run.run("B", pkg=a["package"]))
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
    for name in ("decisions.csv", "REPORT.md"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (committed / name).read_text(encoding="utf-8"), f"{name} is stale: re-run python -m identity_bootstrap.shadow --out {committed}"
    review = Path(shadow_run.__file__).parent / "review" / "create_adjudication.csv"
    calibration.write_adjudication(rows, tmp_path / "create_adjudication.csv")
    assert (tmp_path / "create_adjudication.csv").read_text(encoding="utf-8") == review.read_text(encoding="utf-8"), "create_adjudication.csv is stale"


@needs_package
def test_the_adjudication_artifact_covers_every_create_and_leaves_the_owner_label_blank(built):
    a, _, _, rows = built
    creates = {d["subject"]["entity_id"] for d in a["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    path = Path(shadow_run.__file__).parent / "review" / "create_adjudication.csv"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# owner_label must be one of: TRUE_NEW_IDENTITY | EXISTING_IDENTITY | VARIANT_TRIM_CODE | AMBIGUOUS")
    got = list(csv.DictReader(text.splitlines()[1:]))
    assert {r["external_id"] for r in got} == creates and len(got) == len(creates) == 67
    needed = {"provider", "external_id", "brand", "name", "proposed_canonical_id", "first_seen", "last_seen", "lifetime_units", "last12_units", "nearest_existing_identities",
              "relation_evidence", "lineage_state", "shape_flags", "evidence_tier", "machine_decision", "analyst_note", "owner_label"}
    assert needed <= set(got[0])
    assert all(r["owner_label"] == "" for r in got), "the owner fills owner_label; the shadow run must never pre-fill it"
    assert all(r["provider"] == "ice" and r["machine_decision"].startswith("CREATE_IDENTITY") for r in got)


@needs_package
def test_milestone_3_removed_creates_are_attributed_to_the_new_rules(built):
    _, _, summary, _ = built
    attr = summary["m3"]["removed_create_attribution"]
    assert {r for rules in attr.values() for r in rules} == {"R1_hyphenated_code", "R2_glued_powertrain_suffix", "R4_displacement_trim_code", "TRUNCATION_soft_signal"}
    assert sum(1 for r in attr.values() if r == ["R1_hyphenated_code"]) == 7
    assert attr["jac-jac-t8ev"] == ["R2_glued_powertrain_suffix"] and attr["mclaren-mclaren-750s"] == ["R4_displacement_trim_code"]
    assert summary["m3"]["diff"]["A"]["create_added"] == [] and summary["m3"]["diff"]["B"]["create_added"] == []
    assert summary["m3"]["universe"]["create_removed_by_the_fuller_universe"] == [] and summary["m3"]["universe"]["create_added_by_the_fuller_universe"] == []
    assert "d-max" not in " ".join(summary["m3"]["rule_effects"]["R1_hyphenated_code"]["created_off_not_created_on"])


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
    assert set(r6) == creates
    assert all(row[1] == "PROPOSED" for rows in r6.values() for row in rows), "no remaining CREATE group has an approved/matched legacy R6 row"
